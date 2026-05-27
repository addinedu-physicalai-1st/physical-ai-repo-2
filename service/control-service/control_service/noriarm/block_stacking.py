"""블럭쌓기 세션 매니저 + REST/SSE 라우터.

흐름:
  POST .../sessions          → BlockStackingSession (status=created)
  POST .../sessions/{id}/rps → bringup 종료 → rps_player.py (lerobot 직접, ROS 없음).
  POST .../sessions/{id}/start → rps_proc 종료 대기 → camera_tuner.py --apply →
                                  runner_entry.py (ACT 추론 + 홈 복귀 자동 감지).
  GET  .../sessions/{id}/events → SSE — home_event (홈 복귀 횟수) + keepalive.
  DELETE .../sessions/{id}   → runner_entry SIGTERM → bringup 재기동.

"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .block_stacking_process import RunnerProcess

# block_stacking 게임 자산 디렉토리.
_REPO_ROOT = Path(__file__).resolve().parents[4]  # /home/s/pingdergarten
_GAME_DIR = (
    _REPO_ROOT
    / "controller"
    / "noriarm-controller"
    / "src"
    / "noriarm_framework"
    / "noriarm_framework"
    / "games"
    / "block_stacking"
)
_CAMERA_TUNER = _GAME_DIR / "camera_tuner.py"
_RPS_PLAYER = _GAME_DIR / "rps_player.py"
_RUNNER_ENTRY = _GAME_DIR / "runner_entry.py"
_DEVICE_NORIARM_SH = _REPO_ROOT / "scripts" / "device-noriarm.sh"
_BRINGUP_TMUX_SESSION = "noriarm-device"

# noriarm_framework 이 pingdergarten venv 에 설치되지 않으므로 PYTHONPATH 주입.
_NORIARM_SRC = str(
    _REPO_ROOT / "controller" / "noriarm-controller" / "src" / "noriarm_framework"
)


def _runner_env_extra() -> dict[str, str]:
    existing = os.environ.get("PYTHONPATH", "")
    pp = f"{_NORIARM_SRC}:{existing}" if existing else _NORIARM_SRC
    return {"PYTHONPATH": pp}


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/games/block-stacking", tags=["noriarm"])


@dataclass
class BlockStackingSession:
    session_id: str
    status: str = "created"  # created / rps / playing / done / error
    events: list[dict] = field(default_factory=list)
    _queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=64))
    process: Any = None   # RunnerProcess (runner_entry.py)
    rps_proc: Any = None  # rps_player.py asyncio.subprocess.Process

    async def next_event(self, *, timeout_s: float) -> dict | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return None

    def push_event(self, ev: dict) -> None:
        try:
            self._queue.put_nowait(ev)
        except asyncio.QueueFull:
            pass


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, BlockStackingSession] = {}

    def create(self) -> BlockStackingSession:
        sid = uuid.uuid4().hex[:12]
        s = BlockStackingSession(session_id=sid)
        self._sessions[sid] = s
        return s

    def get(self, sid: str) -> BlockStackingSession | None:
        return self._sessions.get(sid)

    def remove(self, sid: str) -> None:
        self._sessions.pop(sid, None)


_store = SessionStore()


def _session_or_404(sid: str) -> BlockStackingSession:
    s = _store.get(sid)
    if s is None:
        raise HTTPException(404, f"session {sid} 없음")
    return s


async def _kill_bringup() -> None:
    try:
        p = await asyncio.create_subprocess_exec(
            "tmux", "kill-session", "-t", _BRINGUP_TMUX_SESSION,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await p.wait()
    except Exception:
        pass


async def _kill_stale_processes() -> None:
    """runner_entry / rps_player 잔여 프로세스 강제 종료 + 스토어 세션 정리."""
    # 스토어에 남은 세션 종료
    for sid, session in list(_store._sessions.items()):
        runner: RunnerProcess | None = session.process
        if runner is not None:
            try:
                await runner.terminate()
            except Exception:
                pass
        if session.rps_proc is not None:
            try:
                session.rps_proc.kill()
            except Exception:
                pass
        _store.remove(sid)

    # pkill 로 OS 레벨 잔여 프로세스 제거
    for script in ("runner_entry.py", "rps_player.py"):
        try:
            p = await asyncio.create_subprocess_exec(
                "pkill", "-9", "-f", script,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await p.wait()
        except Exception:
            pass
    await asyncio.sleep(0.5)


@router.post("/sessions")
async def create_session() -> dict:
    await _kill_stale_processes()
    s = _store.create()
    return {"session_id": s.session_id, "status": s.status}


@router.post("/sessions/{sid}/rps")
async def play_rps(sid: str) -> dict:
    session = _session_or_404(sid)

    # bringup 종료 — rps_player 가 /dev/omx_follower 단독 점유.
    logger.warning("[block-stacking] bringup 종료 (rps 전)")
    await _kill_bringup()
    await asyncio.sleep(1.5)

    # rps_player.py fire-and-forget
    if _RPS_PLAYER.exists():
        try:
            rps_proc = await asyncio.create_subprocess_exec(
                sys.executable, str(_RPS_PLAYER), "/dev/omx_follower",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            session.rps_proc = rps_proc
            logger.warning("[block-stacking] rps_player PID=%s", rps_proc.pid)
        except Exception as e:
            logger.warning("[block-stacking] rps_player 실행 실패: %s", e)
    else:
        logger.warning("[block-stacking] %s 없음 — RPS skip", _RPS_PLAYER)

    session.status = "rps"
    return {"session_id": sid, "status": session.status}


@router.post("/sessions/{sid}/start")
async def start_play(sid: str) -> dict:
    session = _session_or_404(sid)

    # rps_player 가 아직 실행 중이면 최대 10s 대기.
    if session.rps_proc is not None and session.rps_proc.returncode is None:
        logger.warning("[block-stacking] rps_player 종료 대기...")
        try:
            await asyncio.wait_for(session.rps_proc.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("[block-stacking] rps_player timeout — 강제 종료")
            session.rps_proc.kill()
    session.rps_proc = None

    # 카메라 v4l2 세팅.
    if _CAMERA_TUNER.exists():
        logger.warning("[block-stacking] camera_tuner.py front --apply")
        try:
            tuner = await asyncio.create_subprocess_exec(
                sys.executable, str(_CAMERA_TUNER), "front", "--apply",
                cwd=str(_GAME_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(tuner.communicate(), timeout=30.0)
            if stdout:
                logger.warning("[block-stacking] camera_tuner: %s", stdout.decode(errors="replace").strip())
        except Exception as e:
            logger.warning("[block-stacking] camera_tuner 실패: %s", e)
    else:
        logger.warning("[block-stacking] %s 없음 — 카메라 세팅 skip", _CAMERA_TUNER)

    # runner_entry.py 시작 — ACT 추론 + 홈 복귀 자동 감지.
    if not _RUNNER_ENTRY.exists():
        session.status = "error"
        raise HTTPException(500, f"runner_entry.py 없음: {_RUNNER_ENTRY}")

    def _on_event(ev: dict) -> None:
        session.push_event(ev)

    runner = RunnerProcess(
        [sys.executable, str(_RUNNER_ENTRY)],
        env_extra=_runner_env_extra(),
        on_event=_on_event,
    )
    try:
        await runner.start()
    except Exception as e:
        session.status = "error"
        raise HTTPException(500, f"runner_entry 시작 실패: {e}") from e

    logger.warning("[block-stacking] runner_entry 시작 — ACT 모델 로드 대기 (최대 120s)...")
    if not await runner.wait_ready(timeout_s=120.0):
        session.status = "error"
        await runner.terminate()
        raise HTTPException(500, "runner_entry READY timeout — ACT 모델 로드 실패")

    await runner.send_start()
    session.process = runner
    session.status = "playing"
    logger.warning("[block-stacking] runner_entry START 전송 — 추론 루프 시작")

    # 카메라 오픈 후 v4l2 설정이 리셋될 수 있어 3s 후 재적용.
    async def _reapply_v4l2() -> None:
        await asyncio.sleep(3.0)
        if _CAMERA_TUNER.exists():
            try:
                p = await asyncio.create_subprocess_exec(
                    sys.executable, str(_CAMERA_TUNER), "front", "--apply",
                    cwd=str(_GAME_DIR),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                out, _ = await asyncio.wait_for(p.communicate(), timeout=15.0)
                if out:
                    logger.warning("[block-stacking] v4l2 재적용: %s", out.decode(errors="replace").strip())
            except Exception as e:
                logger.warning("[block-stacking] v4l2 재적용 실패: %s", e)

    asyncio.create_task(_reapply_v4l2())

    return {"session_id": sid, "status": session.status}


@router.delete("/sessions/{sid}")
async def end_session(sid: str) -> dict:
    session = _store.get(sid)
    if session is None:
        return {"ok": True}
    session.status = "done"

    # rps_player 혹시 아직 살아있으면 종료.
    if session.rps_proc is not None:
        try:
            session.rps_proc.kill()
        except Exception:
            pass

    # runner_entry SIGTERM → robot.disconnect() 후 종료.
    runner: RunnerProcess | None = session.process
    if runner is not None:
        try:
            await runner.terminate()
            code = await runner.wait_exit(timeout_s=10.0)
            if code is None:
                logger.warning("[block-stacking] SIGTERM 10s timeout — SIGKILL")
                if runner._proc is not None:
                    try:
                        runner._proc.kill()
                    except Exception:
                        pass
        except Exception:
            logger.warning("[block-stacking] runner 종료 중 예외 (무시)")

    # bringup 재기동.
    if _DEVICE_NORIARM_SH.exists():
        logger.warning("[block-stacking] bringup 재기동")
        try:
            await asyncio.create_subprocess_exec(
                "bash", str(_DEVICE_NORIARM_SH),
                cwd=str(_REPO_ROOT),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            logger.warning("[block-stacking] bringup 재기동 실패: %s", e)

    _store.remove(sid)
    return {"ok": True}


@router.get("/sessions/{sid}/events")
async def session_events(sid: str, req: Request) -> StreamingResponse:
    session = _session_or_404(sid)
    return StreamingResponse(
        _event_stream(req, session),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _event_stream(req: Request, session: BlockStackingSession) -> AsyncIterator[str]:
    yield ": connected\n\n"
    for ev in session.events:
        yield f"data: {json.dumps(ev)}\n\n"
    while True:
        if await req.is_disconnected():
            break
        ev = await session.next_event(timeout_s=15.0)
        if ev is None:
            yield ": keepalive\n\n"
            continue
        yield f"data: {json.dumps(ev)}\n\n"
        if ev.get("type") == "done":
            break
