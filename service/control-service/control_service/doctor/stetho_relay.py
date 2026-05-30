"""EduPing 청진기(FSR) → control 서버 WebSocket bridge.

흐름:
    [EduPing 머신]
      fsr_bridge_node → /eduping/stethoscope/fsr_raw (ROS, 로컬)
                            │
                            ▼
      fsr_ws_uploader_node (eduping_stethoscope)
        ROS sub → WebSocket client
                            │
                            ▼  (cross-machine: WiFi/LAN)
    [Control 서버]
      /ws/eduping/stetho?role=producer  ← uploader 가 push
            │
            ▼
      StethoHub.latest_raw  ← doctor push loop 가 polling → doctor UI footer

a-2 (eduping↔doctor ROS 도메인 분리) 에서 FSR 만 ROS DDS 에 의존하면 cross-machine
도달 안 함 — 카메라(/ws/eduping/rgb)와 동일하게 WebSocket 으로 우회.

Wire format: 텍스트 10진 정수 (raw ADC, 0..1023). consumer fan-out 없음 — push loop polling.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

log = logging.getLogger(__name__)


class StethoHub:
    """FSR raw 최신값 보관. producer 0~1 (uploader). consumer 없음 (push loop 가 polling)."""

    def __init__(self) -> None:
        self._producer: WebSocket | None = None
        self._latest_raw: int | None = None

    @property
    def latest_raw(self) -> int | None:
        return self._latest_raw

    async def register_producer(self, ws: WebSocket) -> None:
        prev = self._producer
        if prev is not None:
            try:
                await prev.close(code=status.WS_1000_NORMAL_CLOSURE)
            except Exception:
                pass
        self._producer = ws
        log.info("eduping_stetho producer registered")

    async def unregister_producer(self, ws: WebSocket) -> None:
        if self._producer is ws:
            self._producer = None
            # producer 끊기면 stale 값을 계속 보내지 않도록 clear.
            self._latest_raw = None
            log.info("eduping_stetho producer gone")

    def update(self, raw: int) -> None:
        self._latest_raw = raw


def build_router(hub: StethoHub) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws/eduping/stetho")
    async def ws_handler(  # noqa: ANN202
        ws: WebSocket,
        role: str | None = Query(default=None),
    ) -> None:
        if role != "producer":
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.accept()
        await hub.register_producer(ws)
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                text = msg.get("text")
                if text is None:
                    raw_bytes = msg.get("bytes")
                    text = raw_bytes.decode("ascii", "ignore") if raw_bytes else None
                if not text:
                    continue
                try:
                    hub.update(int(text.strip()))
                except (ValueError, TypeError):
                    pass
        except WebSocketDisconnect:
            pass
        finally:
            await hub.unregister_producer(ws)

    return r
