"""EduPing D435 RGB → 브라우저 fan-out relay.

흐름:
    [EduPing 머신]
      realsense2_camera_node → /d435/color/image_raw (ROS, 로컬)
                                  │
                                  ▼
      d435_rgb_uploader_node (eduarm)
        cv_bridge → JPEG → WebSocket client
                            │
                            ▼  (cross-machine: WiFi/LAN)
    [Control 서버]
      /ws/eduping/rgb?role=producer  ← uploader 가 push
            │
            ▼
      EdupingRgbHub.push_frame_async
            │
            ▼
      /ws/eduping/rgb?role=consumer
        ├─ doctor portal-web → 우측 절반 (child 환경 영상)
        └─ robot-web 건강검진 → 자기 PIP

Wire format: 순수 JPEG bytes.

ROS DDS 로 이미지 cross-machine 보내면 WiFi 마비 — WebSocket 으로 우회.
"""
from __future__ import annotations

import logging
from typing import Set

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

log = logging.getLogger(__name__)


class EdupingRgbHub:
    """D435 RGB JPEG frame fan-out. producer 0~1 (uploader), consumer N (브라우저)."""

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
        log.info("eduping_rgb producer registered")

    async def unregister_producer(self, ws: WebSocket) -> None:
        if self._producer is ws:
            self._producer = None
            log.info("eduping_rgb producer gone")

    async def register_consumer(self, ws: WebSocket) -> None:
        self._consumers.add(ws)
        last = self._last_frame
        if last is not None:
            try:
                await ws.send_bytes(last)
            except Exception as e:
                log.warning("eduping_rgb initial send failed: %s", e)

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


def build_router(hub: EdupingRgbHub) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws/eduping/rgb")
    async def ws_handler(  # noqa: ANN202
        ws: WebSocket,
        role: str | None = Query(default=None),
    ) -> None:
        if role not in ("producer", "consumer"):
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.accept()
        try:
            if role == "producer":
                await hub.register_producer(ws)
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    payload = msg.get("bytes")
                    if payload:
                        await hub.push_frame(payload)
            else:
                await hub.register_consumer(ws)
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
        except WebSocketDisconnect:
            pass
        finally:
            if role == "producer":
                await hub.unregister_producer(ws)
            else:
                await hub.unregister_consumer(ws)

    return r
