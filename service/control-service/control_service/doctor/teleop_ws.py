"""WSS handler for doctor teleop binary protocol.

이 모듈은 ROS 와 직접 통신하지 않는다 — DoctorTeleopHub 의 콜백/큐 인터페이스를
통해 ros_bridge 모듈과 분리. asyncio 핸들러 안에서 rclpy 직접 호출 금지
(기존 teleop/router.py 와 같은 규칙).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import defaultdict
from typing import Callable

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from control_service.streaming.teleop_protocol import (
    StateFrame, TargetFrame,
    decode_target, encode_state,
)

log = logging.getLogger(__name__)

TargetCb = Callable[[str, TargetFrame], None]
EventCb = Callable[[str, dict], None]

# (loop, ws) 페어 — publish_state 가 올바른 loop 에서 send_bytes 를 schedule 하기 위해 저장.
_ConnEntry = tuple[asyncio.AbstractEventLoop, WebSocket]


class DoctorTeleopHub:
    """eduping_id 별 WS connection set + 콜백 라우팅.

    on_target / on_event 콜백은 ros_bridge 가 등록.
    publish_state 는 ros_bridge 의 state subscriber 가 호출.
    """

    def __init__(self) -> None:
        self._conns: dict[str, list[_ConnEntry]] = defaultdict(list)
        self._conns_lock = threading.Lock()
        self._target_cb: TargetCb | None = None
        self._event_cb: EventCb | None = None

    def on_target(self, cb: TargetCb) -> None:
        self._target_cb = cb

    def on_event(self, cb: EventCb) -> None:
        self._event_cb = cb

    async def register(self, eduping_id: str, ws: WebSocket) -> None:
        loop = asyncio.get_running_loop()
        with self._conns_lock:
            self._conns[eduping_id].append((loop, ws))

    async def unregister(self, eduping_id: str, ws: WebSocket) -> None:
        with self._conns_lock:
            entries = self._conns.get(eduping_id, [])
            self._conns[eduping_id] = [(l, w) for l, w in entries if w is not ws]
            if not self._conns[eduping_id]:
                self._conns.pop(eduping_id, None)

    def publish_state(self, eduping_id: str, frame: StateFrame) -> None:
        """동기 진입점 — ros_bridge thread 또는 테스트 thread 에서 호출 가능.

        각 연결에 저장된 event loop 로 ws.send_bytes 를 안전하게 schedule.
        실제 send 는 해당 loop 의 asyncio task 로 실행되므로 스레드 안전.
        """
        buf = encode_state(frame)
        with self._conns_lock:
            entries = list(self._conns.get(eduping_id, ()))
        for loop, ws in entries:
            fut = asyncio.run_coroutine_threadsafe(ws.send_bytes(buf), loop)
            # 결과를 기다리지 않음 — fire-and-forget. 에러는 예외 없이 로그만.
            def _log_error(f: asyncio.Future, _ws: WebSocket = ws) -> None:
                try:
                    f.result()
                except Exception as e:
                    log.warning("publish_state send failed for %s: %s", _ws, e)
            fut.add_done_callback(_log_error)

    def publish_event(self, eduping_id: str, msg: dict) -> None:
        """서버→UI 텍스트(JSON) 프레임. publish_state 와 동일한 thread-safe 패턴.

        ros_bridge thread 등 비-asyncio thread 에서 호출 가능 — 각 연결에 저장된
        event loop 로 ws.send_text 를 schedule (fire-and-forget, 에러는 로그만).
        """
        text = json.dumps(msg)
        with self._conns_lock:
            entries = list(self._conns.get(eduping_id, ()))
        for loop, ws in entries:
            fut = asyncio.run_coroutine_threadsafe(ws.send_text(text), loop)

            def _log_error(f: asyncio.Future, _ws: WebSocket = ws) -> None:
                try:
                    f.result()
                except Exception as e:
                    log.warning("publish_event send failed for %s: %s", _ws, e)
            fut.add_done_callback(_log_error)

    def active_eduping_ids(self) -> list[str]:
        """현재 연결된 eduping_id 목록 (복사본 반환 — thread-safe)."""
        with self._conns_lock:
            return list(self._conns.keys())

    def _dispatch_target(self, eduping_id: str, frame: TargetFrame) -> None:
        if self._target_cb:
            self._target_cb(eduping_id, frame)

    def _dispatch_event(self, eduping_id: str, msg: dict) -> None:
        if self._event_cb:
            self._event_cb(eduping_id, msg)


def build_router(hub: DoctorTeleopHub) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws/doctor/teleop")
    async def doctor_teleop_ws(
        ws: WebSocket,
        eduping_id: str | None = Query(default=None),
    ) -> None:
        if not eduping_id:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.accept()
        await hub.register(eduping_id, ws)
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if "bytes" in msg and msg["bytes"] is not None:
                    try:
                        frame = decode_target(msg["bytes"])
                        hub._dispatch_target(eduping_id, frame)
                    except ValueError as e:
                        log.warning("bad target frame from %s: %s", eduping_id, e)
                elif "text" in msg and msg["text"] is not None:
                    try:
                        evt = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        log.warning("bad json from %s", eduping_id)
                        continue
                    if isinstance(evt, dict):
                        hub._dispatch_event(eduping_id, evt)
        except WebSocketDisconnect:
            pass
        finally:
            await hub.unregister(eduping_id, ws)

    return r
