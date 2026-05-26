"""블럭쌓기 세션 매니저 + REST/SSE 라우터.

흐름:
  POST .../sessions          → BlockStackingSession (status=created)
  POST .../sessions/{id}/rps → bringup 종료 → rps_player.py (lerobot 직접, ROS 없음).
  POST .../sessions/{id}/start → rps_proc 종료 대기 → camera_tuner.py --apply →
                                  /dev/shm/eval_stacking 정리 → lerobot-record (gnome-terminal).
  GET  .../sessions/{id}/events → SSE — home_event (에피소드 완료 parquet 수) + keepalive.
  DELETE .../sessions/{id}   → lerobot-record SIGINT → bringup 재기동.

"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import signal
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

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
_DEVICE_NORIARM_SH = _REPO_ROOT / "scripts" / "device-noriarm.sh"
_RAM_DISK_DIR = "/dev/shm/eval_stacking"
_BRINGUP_TMUX_SESSION = "noriarm-device"

# 카메라 by-id (원본 run_inference.sh 기준 — by-path보다 안정적).
_FRONT_CAM = "/dev/v4l/by-id/usb-Alcorlink_Corp._USB_2.0_Camera-video-index0"
_WRIST_CAM = "/dev/v4l/by-id/usb-Sonix_Technology_Co.__Ltd._USB_2.0_Camera_SN0001-video-index0"


def _lerobot_record_argv() -> list[str]:
    cameras = {
        "front": {
            "type": "opencv",
            "index_or_path": _FRONT_CAM,
            "width": 640, "height": 480, "fps": 30, "fourcc": "MJPG",
        },
        "wrist": {
            "type": "opencv",
            "index_or_path": _WRIST_CAM,
            "width": 640, "height": 480, "fps": 30, "fourcc": "MJPG",
        },
    }
    return [
        "lerobot-record",
        "--robot.type=omx_follower",
        "--robot.port=/dev/omx_follower",
        "--robot.id=omx_follower_arm",
        f"--robot.cameras={json.dumps(cameras)}",
        "--display_data=true",
        "--play_sounds=false",
        "--policy.path=jisoo3/act_game_block_stacking_0520",
        "--policy.temporal_ensemble_coeff=0.01",
        "--policy.n_action_steps=1",
        "--dataset.repo_id=jisoo3/eval_stacking_0520",
        f"--dataset.root={_RAM_DISK_DIR}",
        "--dataset.single_task=Game Block Stacking",
        "--dataset.episode_time_s=500",
        "--dataset.reset_time_s=15",
        "--dataset.push_to_hub=false",
    ]


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/games/block-stacking", tags=["noriarm"])


class _LerobotProxy:
    """gnome-terminal 안에서 도는 lerobot-record PID proxy."""

    def __init__(self, pid: int | None) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def send_signal(self, sig: int) -> None:
        if self.pid is None:
            return
        try:
            os.kill(self.pid, sig)
        except ProcessLookupError:
            self.returncode = 0

    def terminate(self) -> None:
        self.send_signal(signal.SIGTERM)

    def kill(self) -> None:
        self.send_signal(signal.SIGKILL)

    async def wait(self) -> int:
        if self.pid is None:
            self.returncode = 0
            return 0
        while True:
            try:
                os.kill(self.pid, 0)
            except (ProcessLookupError, PermissionError):
                self.returncode = 0
                return 0
            await asyncio.sleep(0.2)


@dataclass
class BlockStackingSession:
    session_id: str
    status: str = "created"  # created / rps / playing / done / error
    events: list[dict] = field(default_factory=list)
    _queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=64))
    process: Any = None   # lerobot-record _LerobotProxy
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


@router.post("/sessions")
async def create_session() -> dict:
    s = _store.create()
    return {"session_id": s.session_id, "status": s.status}


@router.post("/sessions/{sid}/rps")
async def play_rps(sid: str) -> dict:
    session = _session_or_404(sid)

    # bringup 종료 — rps_player 가 /dev/omx_follower 단독 점유.
    logger.warning("[block-stacking] bringup 종료 (rps 전)")
    await _kill_bringup()
    await asyncio.sleep(1.5)

    # rps_player.py fire-and-forget — UI timer 6s 후 /start 가 호출되므로 그때쯤 완료됨.
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

    # RAM disk 정리.
    logger.warning("[block-stacking] %s 정리", _RAM_DISK_DIR)
    rm = await asyncio.create_subprocess_exec(
        "rm", "-rf", _RAM_DISK_DIR,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await rm.wait()

    # lerobot-record — gnome-terminal 새 창 (ROS env 완전 격리).
    argv = _lerobot_record_argv()
    inner_cmd = " ".join(shlex.quote(a) for a in argv)
    pid_file = "/tmp/lerobot.pid"
    log_path = "/tmp/lerobot.log"
    bash_script = (
        f"rm -f {pid_file}; "
        f"({inner_cmd} & echo $! > {pid_file}; wait) 2>&1 | tee {log_path}; "
        f"echo; echo '[lerobot-record 종료 — 창 닫기: Ctrl+D]'; exec bash"
    )
    logger.warning("[block-stacking] gnome-terminal 에서 lerobot-record 시작")
    try:
        term_proc = await asyncio.create_subprocess_exec(
            "gnome-terminal", "--title=NoriArm 블럭쌓기 추론", "--",
            "bash", "-c", bash_script,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as e:
        session.status = "error"
        raise HTTPException(500, f"gnome-terminal 실행 불가: {e}") from e

    # lerobot PID 파일 대기.
    lerobot_pid: int | None = None
    for _ in range(30):
        await asyncio.sleep(0.1)
        try:
            with open(pid_file) as f:
                lerobot_pid = int(f.read().strip())
            break
        except (FileNotFoundError, ValueError):
            continue
    logger.warning("[block-stacking] gnome-terminal PID=%s  lerobot PID=%s",
                   term_proc.pid, lerobot_pid)
    session.process = _LerobotProxy(lerobot_pid)
    session.status = "playing"

    # lerobot가 카메라를 열 때 v4l2 설정이 리셋될 수 있어 3s 후 재적용.
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

    # 에피소드 완료(parquet 파일 생성) 감지 → home_event SSE 발행.
    async def _watch_episodes() -> None:
        data_dir = Path(_RAM_DISK_DIR) / "data" / "chunk-000"
        prev_count = 0
        while session.status == "playing":
            await asyncio.sleep(5.0)
            try:
                count = len(list(data_dir.glob("episode_*.parquet")))
                if count > prev_count:
                    prev_count = count
                    session.push_event({"type": "home_event", "count": count})
            except Exception:
                pass

    asyncio.create_task(_reapply_v4l2())
    asyncio.create_task(_watch_episodes())

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

    # lerobot-record SIGINT — disable_torque_on_disconnect 정상 동작.
    proc: Any = session.process
    if proc is not None:
        try:
            if hasattr(proc, "send_signal"):
                proc.send_signal(signal.SIGINT)
            else:
                proc.terminate()
            if hasattr(proc, "wait"):
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10.0)
                except asyncio.TimeoutError:
                    logger.warning("[block-stacking] SIGINT 10s timeout — SIGTERM")
                    if hasattr(proc, "terminate"):
                        proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=3.0)
                    except asyncio.TimeoutError:
                        if hasattr(proc, "kill"):
                            proc.kill()
        except Exception:
            logger.warning("[block-stacking] lerobot 종료 중 예외 (무시)")

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
