"""가게놀이 세션 매니저 + REST/SSE 라우터 (long-lived runner).

UX 목표: 사용자가 "가게놀이" 모드 진입 시 한 번만 무거운 초기화 (모델 + YOLO + 카메라
+ 모터) 후, 매 아이템 클릭은 즉시 시작. 모드 나갈 때만 cleanly disconnect.

수명 모델:
  POST .../sessions              → session 생성 + runner subprocess 1회 spawn (heavy init)
                                    body: {"target": "real"}  (prompt 없음 — serve 에서 받음)
  POST .../sessions/{id}/start   → wait_ready → send_start → "idle" 상태로 PROMPT 대기
  POST .../sessions/{id}/serve   → send_prompt(prompt) — task 1회 실행
                                    body: {"prompt": "give me strawberry"}
                                    runner stdout "TASK_DONE" 받으면 SSE "task_done" push.
  POST .../sessions/{id}/abort   → SIGUSR1 — 진행 중 task 중단 (session 은 살아있음)
  GET  .../sessions/{id}/events  → SSE — task_started / task_done / done push
  DELETE .../sessions/{id}       → send_quit → cleanly disconnect → session 정리

이 패턴은 block_stacking 의 1-task=1-process 와 다름. RunnerProcess 의 send_prompt /
wait_task_done / send_abort / send_quit 메서드는 store_play 만 사용.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from control_service.noriarm.block_stacking_process import RunnerProcess

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/games/store-play", tags=["noriarm"])

READY_TIMEOUT_S = 120.0   # ACT phase5: ~10s + YOLO load + 양팔 connect + 카메라 warmup × 3 (~5s each).
TASK_TIMEOUT_S = 1300.0   # 한 task 최대 시간. game.yaml episode_timeout_s(1000) + sub-realtime
                          # 오버헤드(추론 ~40ms/frame → ~25Hz → 30000 frame≈1200s wall) + 여유.
                          # 이 값보다 episode 가 길면 control 이 task 를 mid-way abort 하니 동기 유지 필수.

# runner_entry 가 LeRobot BiOmxFollower / ultralytics YOLO 등을 import 하므로
# 이들이 설치된 venv 의 Python interpreter 필요. control_service venv 에 없으면
# NORIARM_STOREPLAY_PYTHON 으로 override (예: /home/kyle/venv/store_play/bin/python).
_ENV_PYTHON = "NORIARM_STOREPLAY_PYTHON"
_ENV_PYTHONPATH_EXTRA = "NORIARM_STOREPLAY_PYTHONPATH"



class CreateSessionRequest(BaseModel):
    target: str = Field(default="real", description="'real' | 'sim'")


class ServeRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="task prompt — e.g. 'give me strawberry'")


@dataclass
class StorePlaySession:
    session_id: str
    # 상태:
    #   created   → spawn 됐지만 아직 wait_ready 전
    #   loading   → wait_ready 진행 중 (모델·YOLO·카메라 load)
    #   idle      → PROMPT 대기 (다음 serve 호출 가능)
    #   serving   → 한 task 실행 중
    #   done      → 세션 종료됨 (DELETE 또는 runner 사망)
    #   error     → 실패 상태
    status: str = "created"
    _queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=64))
    process: RunnerProcess | None = None
    _serve_task: asyncio.Task | None = None  # 진행 중 task 의 awaiter — abort 시 cancel 가능.

    def push_event(self, payload: dict) -> None:
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    def push_done(self) -> None:
        if self.status in ("done", "error"):
            return
        self.status = "done"
        ev = {"type": "done"}
        try:
            self._queue.put_nowait(ev)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(ev)
            except Exception:
                pass

    async def next_event(self, *, timeout_s: float) -> dict | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return None

    def cancel_serve(self) -> None:
        if self._serve_task is not None and not self._serve_task.done():
            self._serve_task.cancel()
            self._serve_task = None


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, StorePlaySession] = {}

    def create(self) -> StorePlaySession:
        sid = uuid.uuid4().hex[:12]
        s = StorePlaySession(session_id=sid)
        self._sessions[sid] = s
        return s

    def get(self, sid: str) -> StorePlaySession | None:
        return self._sessions.get(sid)

    def remove(self, sid: str) -> None:
        self._sessions.pop(sid, None)


_store = SessionStore()


def _session_or_404(sid: str) -> StorePlaySession:
    s = _store.get(sid)
    if s is None:
        raise HTTPException(404, f"session {sid} 없음")
    return s


def _runner_argv(target: str) -> list[str]:
    python_bin = os.environ.get(_ENV_PYTHON, sys.executable)
    return [
        python_bin,
        "-m",
        "noriarm_framework.games.store_play.runner_entry",
        "--target",
        target,
    ]


def _runner_env_extra() -> dict[str, str]:
    extra: dict[str, str] = {}
    extra_path = os.environ.get(_ENV_PYTHONPATH_EXTRA)
    if extra_path:
        existing = os.environ.get("PYTHONPATH", "")
        extra["PYTHONPATH"] = f"{extra_path}:{existing}" if existing else extra_path
    return extra


# =================================================================== handlers


@router.post("/sessions")
async def create_session(body: CreateSessionRequest) -> dict:
    """모드 진입 시 1회 호출 — runner spawn (heavy init 시작)."""
    session = _store.create()
    argv = _runner_argv(body.target)
    # runner 도메인 이벤트(bell_rung / missing) → SSE 로 흘림 (session.push_event).
    session.process = RunnerProcess(
        argv, env_extra=_runner_env_extra(), on_event=session.push_event,
    )
    try:
        await session.process.start()
    except Exception as e:
        session.status = "error"
        _store.remove(session.session_id)
        logger.exception("[store_play] 서브프로세스 spawn 실패")
        raise HTTPException(500, f"runner spawn 실패: {e}") from e
    session.status = "loading"
    return {
        "session_id": session.session_id,
        "status": session.status,
        "target": body.target,
    }


@router.post("/sessions/{sid}/start")
async def start_play(sid: str) -> dict:
    """wait_ready (모델·YOLO·카메라·모터 load 완료) → idle 상태."""
    session = _session_or_404(sid)
    if session.process is None:
        raise HTTPException(400, "session 에 연결된 프로세스가 없음")
    if session.status not in ("loading", "created"):
        raise HTTPException(409, f"이미 진행 중인 세션 (status={session.status})")

    ready = await session.process.wait_ready(timeout_s=READY_TIMEOUT_S)
    if not ready:
        session.status = "error"
        await session.process.terminate()
        raise HTTPException(500, f"runner READY 미수신 ({READY_TIMEOUT_S}s 초과)")

    await session.process.send_start()
    session.status = "idle"
    session.push_event({"type": "ready"})
    return {"session_id": sid, "status": session.status}


async def _serve_and_emit(session: StorePlaySession, prompt: str) -> None:
    """PROMPT 보내고 TASK_DONE 대기 → SSE task_done emit."""
    assert session.process is not None
    try:
        await session.process.send_prompt(prompt)
        done = await session.process.wait_task_done(timeout_s=TASK_TIMEOUT_S)
        if not done:
            logger.warning("[store_play] task timeout: prompt=%r", prompt)
            session.push_event({"type": "task_timeout", "prompt": prompt})
            # task 강제 중단 — runner 가 다음 PROMPT 받을 수 있도록.
            await session.process.send_abort()
            # abort 후 TASK_DONE 한 번 더 올 수 있어 짧게 흡수.
            await session.process.wait_task_done(timeout_s=5.0)
        else:
            session.push_event({"type": "task_done", "prompt": prompt})
    except asyncio.CancelledError:
        # 외부 (DELETE / abort) 가 cancel — 추가 emit 안 함.
        raise
    except Exception as e:
        logger.exception("[store_play] serve 실패: %s", e)
        session.push_event({"type": "task_error", "prompt": prompt, "error": str(e)})
    finally:
        # serving → idle 복귀 (단, session 이 이미 done 됐으면 그대로).
        if session.status == "serving":
            session.status = "idle"


@router.post("/sessions/{sid}/serve")
async def serve(sid: str, body: ServeRequest) -> dict:
    """현재 idle 인 session 에 task 1회 실행 (async — 함수는 즉시 반환, SSE 로 진행)."""
    session = _session_or_404(sid)
    if session.process is None or session.status != "idle":
        raise HTTPException(409, f"serve 불가 — session status={session.status}. idle 일 때만 가능.")

    session.status = "serving"
    session.push_event({"type": "task_started", "prompt": body.prompt})
    session._serve_task = asyncio.create_task(_serve_and_emit(session, body.prompt))
    return {"session_id": sid, "status": session.status, "prompt": body.prompt}


@router.post("/sessions/{sid}/abort")
async def abort_task(sid: str) -> dict:
    """진행 중 task 만 중단 (session 은 살아서 다음 serve 가능)."""
    session = _session_or_404(sid)
    if session.process is None:
        raise HTTPException(400, "session 에 연결된 프로세스가 없음")
    if session.status == "serving":
        await session.process.send_abort()
        # 직접 status 변경 X — _serve_and_emit 의 finally 가 idle 로 돌려놓음.
    return {"session_id": sid, "status": session.status}


@router.delete("/sessions/{sid}")
async def end_session(sid: str) -> dict:
    """cleanly 종료 — send_quit 후 wait_exit. timeout 시 terminate 폴백."""
    session = _store.get(sid)
    if session is None:
        return {"ok": True}
    session.cancel_serve()
    if session.process is not None:
        # 진행 중 task 있으면 abort 먼저 (runner 가 idle 로 돌아가 QUIT 받기 쉬워짐).
        if session.status == "serving":
            await session.process.send_abort()
        await session.process.send_quit()
        exit_code = await session.process.wait_exit(timeout_s=10.0)
        if exit_code is None:
            logger.warning("[store_play] QUIT 후 미응답 — SIGTERM 폴백")
            await session.process.terminate()
            await session.process.wait_exit(timeout_s=5.0)
    session.push_done()
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


async def _event_stream(req: Request, session: StorePlaySession) -> AsyncIterator[str]:
    yield ": connected\n\n"
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
