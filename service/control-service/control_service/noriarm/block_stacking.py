"""블럭쌓기 세션 매니저 + REST/SSE 라우터.

흐름:
  POST .../sessions          → BlockStackingSession (status=created)
  POST .../sessions/{id}/rps → bridge.play_rps_paper() + RunnerProcess.start()
                                (서브프로세스가 ACT 모델 로드 — RPS 재생 시간과 겹침)
  POST .../sessions/{id}/start → RunnerProcess.send_start() — ACT 게임 루프 진입.
                                  동시에 bridge HOME 이벤트 listener 부착.
  GET  .../sessions/{id}/events → SSE — home_event / done push.
  home count = 2 도달 시 RunnerProcess.terminate() + SSE done.
  DELETE .../sessions/{id}   → listener unsubscribe + process terminate + 정리.
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
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from control_service.noriarm.block_stacking_process import RunnerProcess
from control_service.noriarm.ros_bridge import NoriarmRosBridge

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/games/block-stacking", tags=["noriarm"])

HOME_EVENTS_TO_END = 2
READY_TIMEOUT_S = 60.0  # ACT 모델 로드 최대 대기 (대형 체크포인트 가정).


@dataclass
class BlockStackingSession:
    session_id: str
    status: str = "created"  # created / rps / playing / done / error
    home_event_count: int = 0
    events: list[dict] = field(default_factory=list)
    _queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=64))
    unsubscribe: callable | None = None  # type: ignore[assignment]
    process: RunnerProcess | None = None

    def is_done(self) -> bool:
        return self.home_event_count >= HOME_EVENTS_TO_END

    def on_home_event(self, count: int) -> None:
        self.home_event_count = count
        payload = {"type": "home_event", "count": count}
        self.events.append(payload)
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass
        if self.is_done():
            self.status = "done"
            done_payload = {"type": "done", "count": count}
            self.events.append(done_payload)
            try:
                self._queue.put_nowait(done_payload)
            except asyncio.QueueFull:
                # drain one slot then force-insert — "done" must not be lost
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(done_payload)
                except Exception:
                    pass

    async def next_event(self, *, timeout_s: float) -> dict | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout_s)
        except asyncio.TimeoutError:
            return None


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


def _bridge(req: Request) -> NoriarmRosBridge:
    b = getattr(req.app.state, "noriarm_bridge", None)
    if b is None:
        raise HTTPException(503, "noriarm bridge 미초기화")
    return b


def _session_or_404(sid: str) -> BlockStackingSession:
    s = _store.get(sid)
    if s is None:
        raise HTTPException(404, f"session {sid} 없음")
    return s


def _runner_argv(target: str) -> list[str]:
    """python -m noriarm_framework.games.block_stacking.runner_entry --target ..."""
    return [
        sys.executable,
        "-m",
        "noriarm_framework.games.block_stacking.runner_entry",
        "--target",
        target,
    ]


@router.post("/sessions")
async def create_session() -> dict:
    s = _store.create()
    return {"session_id": s.session_id, "status": s.status}


@router.post("/sessions/{sid}/rps")
async def play_rps(sid: str, req: Request) -> dict:
    session = _session_or_404(sid)
    bridge = _bridge(req)

    # 1) bridge 가 RPS '보' trajectory 단발 publish (서브프로세스와 무관).
    rps_result = await bridge.play_rps_paper()

    # 2) runner_entry 서브프로세스 spawn — ACT 모델 로드를 RPS 재생 시간 동안 진행.
    target = "real" if bridge._target == "real" else "sim"  # bridge 가 자동 감지한 값
    session.process = RunnerProcess(_runner_argv(target))
    try:
        await session.process.start()
    except Exception as e:
        session.status = "error"
        logger.exception("runner 서브프로세스 spawn 실패")
        raise HTTPException(500, f"runner spawn 실패: {e}") from e
    session.status = "rps"
    return {
        "session_id": sid,
        "status": session.status,
        "subprocess_spawned": True,
        **rps_result,
    }


@router.post("/sessions/{sid}/start")
async def start_play(sid: str, req: Request) -> dict:
    session = _session_or_404(sid)
    bridge = _bridge(req)
    if session.process is None:
        raise HTTPException(400, "/rps 먼저 호출해 서브프로세스를 띄워야 합니다")

    # 1) 서브프로세스가 READY 일 때까지 대기 (모델 로드 완료 신호).
    ready = await session.process.wait_ready(timeout_s=READY_TIMEOUT_S)
    if not ready:
        session.status = "error"
        await session.process.terminate()
        raise HTTPException(500, f"runner READY 미수신 ({READY_TIMEOUT_S}s)")

    # 2) HOME 이벤트 listener 부착 — done 시 process.terminate() 까지 가도록.
    def _on_home(count: int) -> None:
        session.on_home_event(count)
        if session.is_done() and session.process is not None:
            asyncio.create_task(session.process.terminate())

    if session.unsubscribe is not None:
        session.unsubscribe()
    session.unsubscribe = await bridge.start_block_stacking_session(on_home_event=_on_home)

    # 3) 서브프로세스에 "START" — 게임 루프 진입.
    await session.process.send_start()
    session.status = "playing"
    return {"session_id": sid, "status": session.status}


@router.delete("/sessions/{sid}")
async def end_session(sid: str) -> dict:
    session = _store.get(sid)
    if session is None:
        return {"ok": True}
    if session.unsubscribe is not None:
        session.unsubscribe()
        session.unsubscribe = None
    if session.process is not None:
        await session.process.terminate()
        await session.process.wait_exit(timeout_s=5.0)
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
