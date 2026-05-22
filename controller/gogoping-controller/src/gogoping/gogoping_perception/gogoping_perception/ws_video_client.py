"""control-service /ws/video-stream client — perception 노드용.

asyncio 기반 WebSocket client. handshake (hello → hello_ack → subscribe → subscribed)
후 binary frame 수신 시 callback 호출. frame_callback 은 별도 thread 에서 동작하므로
호출 측에서 lock 으로 thread-safety 보장.

ROS DDS 의 image topic multicast 대체 — 단일 TCP connection 으로 영상 받음.
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from typing import Callable, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from gogoping_perception.config import (
    WS_CLIENT_ID,
    WS_CLIENT_KIND,
    WS_RECONNECT_DELAY_S,
    WS_SUBSCRIBE_ROBOT,
    WS_SUBSCRIBE_STREAM,
    WS_VIDEO_URL,
)


WS_FRAME_HEADER_FMT = "!BBBBIQI"
WS_FRAME_HEADER_SIZE = 20
WS_MSG_VIDEO_FRAME = 0x10


FrameCallback = Callable[[bytes, int, int], None]
"""(jpeg_bytes, frame_seq, ts_ms) → None. 호출 측에서 cv2.imdecode 후 inference."""


class WSVideoClient:
    def __init__(
        self,
        frame_callback: FrameCallback,
        logger: Optional[logging.Logger] = None,
        url: str = WS_VIDEO_URL,
    ) -> None:
        self._frame_callback = frame_callback
        self._logger = logger or logging.getLogger(__name__)
        self._url = url
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        while not self._stopped:
            try:
                await self._connect_once()
            except (OSError, ConnectionClosed) as e:
                # ROS RcutilsLogger 는 % format 인자 안 받음 → f-string 으로 미리 포맷.
                self._logger.warning(
                    f"WS video client disconnected: {e} — reconnecting in {WS_RECONNECT_DELAY_S:.1f}s"
                )
            except Exception as e:  # noqa: BLE001
                self._logger.warning(f"WS video client error: {e}")
            if self._stopped:
                break
            await asyncio.sleep(WS_RECONNECT_DELAY_S)

    async def _connect_once(self) -> None:
        async with websockets.connect(self._url) as ws:
            welcome_raw = await ws.recv()
            welcome = json.loads(welcome_raw)
            if welcome.get("type") != "welcome":
                raise RuntimeError(f"expected welcome, got {welcome.get('type')}")

            await ws.send(json.dumps({
                "type": "hello",
                "client_id": WS_CLIENT_ID,
                "client_kind": WS_CLIENT_KIND,
                "ts_ms": int(time.time() * 1000),
            }))

            ack_raw = await ws.recv()
            ack = json.loads(ack_raw)
            if ack.get("type") != "hello_ack":
                raise RuntimeError(f"expected hello_ack, got {ack.get('type')}")

            await ws.send(json.dumps({
                "type": "subscribe",
                "robot": WS_SUBSCRIBE_ROBOT,
                "stream": WS_SUBSCRIBE_STREAM,
                "ts_ms": int(time.time() * 1000),
            }))

            sub_ack_raw = await ws.recv()
            sub_ack = json.loads(sub_ack_raw)
            if sub_ack.get("type") != "subscribed":
                self._logger.warning(f"expected subscribed, got {sub_ack}")

            self._logger.info(
                f"WS video client connected: subscribed to robot={WS_SUBSCRIBE_ROBOT} stream={WS_SUBSCRIBE_STREAM}"
            )

            async for msg in ws:
                if self._stopped:
                    break
                if isinstance(msg, bytes):
                    self._handle_binary(msg)
                else:
                    await self._handle_text(ws, msg)

    def _handle_binary(self, data: bytes) -> None:
        if len(data) < WS_FRAME_HEADER_SIZE:
            return
        try:
            msg_type, robot_id, stream_id, _reserved, frame_seq, ts_ms, jpeg_size = struct.unpack(
                WS_FRAME_HEADER_FMT, data[:WS_FRAME_HEADER_SIZE],
            )
        except struct.error:
            return
        if msg_type != WS_MSG_VIDEO_FRAME:
            return
        if jpeg_size != len(data) - WS_FRAME_HEADER_SIZE:
            return
        jpeg = data[WS_FRAME_HEADER_SIZE:]
        try:
            self._frame_callback(jpeg, frame_seq, ts_ms)
        except Exception as e:  # noqa: BLE001
            self._logger.warning(f"frame_callback error: {e}")

    async def _handle_text(self, ws, msg: str) -> None:
        try:
            payload = json.loads(msg)
        except json.JSONDecodeError:
            return
        if payload.get("type") == "ping":
            await ws.send(json.dumps({
                "type": "pong",
                "ts_ms": int(time.time() * 1000),
            }))
