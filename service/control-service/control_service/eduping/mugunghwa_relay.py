"""무궁화 device-local perception relay.

두 채널:
  /ws/eduping/mugunghwa          JSON 이벤트 — robot(perception 노드) ↔ ui(robot-web) forward
  /ws/eduping/mugunghwa/video    JPEG fan-out — producer(노드) → consumers(robot-web PIP)

순수 중계 — 파싱/판정/인코딩 없음. 노드가 사람/움직임을 device-local 판정하고
이벤트/영상만 올린다.
"""
from __future__ import annotations

import json
import logging
from typing import Set

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

log = logging.getLogger(__name__)

EVENT_ROLES = ("robot", "ui")


class MugunghwaEventHub:
    """robot ↔ ui 한 명씩 보관, 한쪽 메시지를 반대편으로 forward."""

    def __init__(self) -> None:
        self._peers: dict[str, WebSocket] = {}

    async def register(self, role: str, ws: WebSocket) -> None:
        prev = self._peers.get(role)
        if prev is not None:
            try:
                await prev.close(code=status.WS_1000_NORMAL_CLOSURE)
            except Exception:
                pass
        self._peers[role] = ws
        log.info("mugunghwa event %s registered (peers=%s)", role, list(self._peers))
        await self._broadcast_presence()

    async def unregister(self, role: str, ws: WebSocket) -> None:
        if self._peers.get(role) is ws:
            del self._peers[role]
            log.info("mugunghwa event %s gone", role)
            await self._broadcast_presence()

    async def _broadcast_presence(self) -> None:
        for role, ws in list(self._peers.items()):
            other = "ui" if role == "robot" else "robot"
            payload = json.dumps({"type": "peer", "present": other in self._peers})
            try:
                await ws.send_text(payload)
            except Exception:
                pass

    async def forward(self, from_role: str, message: str) -> None:
        other = "ui" if from_role == "robot" else "robot"
        peer = self._peers.get(other)
        if peer is None:
            return
        try:
            await peer.send_text(message)
        except Exception as e:
            log.warning("mugunghwa forward to %s failed: %s", other, e)


class MugunghwaVideoHub:
    """JPEG frame fan-out. producer 0~1 (노드), consumer N (브라우저 PIP)."""

    def __init__(self) -> None:
        self._producer: WebSocket | None = None
        self._consumers: Set[WebSocket] = set()
        self._last_frame: bytes | None = None

    async def register_producer(self, ws: WebSocket) -> None:
        prev = self._producer
        if prev is not None:
            try:
                await prev.close(code=status.WS_1000_NORMAL_CLOSURE)
            except Exception:
                pass
        self._producer = ws
        log.info("mugunghwa video producer registered")

    async def unregister_producer(self, ws: WebSocket) -> None:
        if self._producer is ws:
            self._producer = None
            log.info("mugunghwa video producer gone")

    async def register_consumer(self, ws: WebSocket) -> None:
        self._consumers.add(ws)
        last = self._last_frame
        if last is not None:
            try:
                await ws.send_bytes(last)
            except Exception as e:
                log.warning("mugunghwa video initial send failed: %s", e)

    async def unregister_consumer(self, ws: WebSocket) -> None:
        self._consumers.discard(ws)

    async def push_frame(self, frame: bytes) -> None:
        self._last_frame = frame
        dead: list[WebSocket] = []
        for ws in list(self._consumers):
            try:
                await ws.send_bytes(frame)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._consumers.discard(ws)


def build_router(event_hub: MugunghwaEventHub, video_hub: MugunghwaVideoHub) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws/eduping/mugunghwa")
    async def event_ws(  # noqa: ANN202
        ws: WebSocket,
        role: str | None = Query(default=None),
    ) -> None:
        if role not in EVENT_ROLES:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.accept()
        try:
            await event_hub.register(role, ws)
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                text = msg.get("text")
                if text:
                    await event_hub.forward(role, text)
        except WebSocketDisconnect:
            pass
        finally:
            await event_hub.unregister(role, ws)

    @r.websocket("/ws/eduping/mugunghwa/video")
    async def video_ws(  # noqa: ANN202
        ws: WebSocket,
        role: str | None = Query(default=None),
    ) -> None:
        if role not in ("producer", "consumer"):
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.accept()
        try:
            if role == "producer":
                await video_hub.register_producer(ws)
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    payload = msg.get("bytes")
                    if payload:
                        await video_hub.push_frame(payload)
            else:
                await video_hub.register_consumer(ws)
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
        except WebSocketDisconnect:
            pass
        finally:
            if role == "producer":
                await video_hub.unregister_producer(ws)
            else:
                await video_hub.unregister_consumer(ws)

    return r
