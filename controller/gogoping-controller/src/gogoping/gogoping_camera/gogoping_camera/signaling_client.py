"""control-service WS /ws/webrtc/signaling 의 producer 측 클라이언트.

프로토콜 (모든 메시지 JSON):
  client → server:
    {"type": "hello", "role": "producer"|"consumer", "peer_id": str}
    {"type": "offer", "sdp": str}
    {"type": "answer", "sdp": str}
    {"type": "ice", "candidate": dict | null}   # null = end-of-candidates
    {"type": "bye"}
  server → client:
    동일 type. server 가 producer ↔ consumer pair 를 매칭해서 forwarding.

본 producer 는 서버에 connect 후 hello 송신, server 가 consumer hello 받으면 producer 에게
"client_connected" 를 forward — producer 가 offer 생성 → server 에 송신 → server 가
consumer 에 forward → answer 반대로 forward → ICE 양방향.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

import websockets
from websockets.asyncio.client import ClientConnection

_log = logging.getLogger("gogoping_camera.signaling_client")

OnMessage = Callable[[dict], Awaitable[None]]


class SignalingClient:
    """WS connect + reconnect + JSON message dispatch.

    on_message 콜백이 server 메시지를 받음. 동일 콜백이 disconnect (None 메시지)
    도 처리.
    """

    def __init__(self, url: str, peer_id: str, on_message: OnMessage) -> None:
        self._url = url
        self._peer_id = peer_id
        self._on_message = on_message
        self._ws: Optional[ClientConnection] = None
        self._stopped = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stopped = True
        if self._ws is not None:
            try:
                await self.send({"type": "bye"})
            except Exception:
                pass
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def send(self, msg: dict) -> None:
        if self._ws is None:
            raise RuntimeError("signaling not connected")
        await self._ws.send(json.dumps(msg))

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stopped:
            try:
                async with websockets.connect(self._url, max_size=2**20) as ws:
                    self._ws = ws
                    backoff = 1.0
                    await ws.send(json.dumps({
                        "type": "hello", "role": "producer", "peer_id": self._peer_id,
                    }))
                    # client-as-offerer 패턴: hello 직후 webrtc_node 에 "connected"
                    # 통보 → webrtc_node 가 자기 PC + offer 만들어 보냄.
                    await self._on_message({"type": "connected"})
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            _log.warning("non-JSON signaling message: %r", raw[:80])
                            continue
                        await self._on_message(msg)
            except Exception as exc:
                if self._stopped:
                    return
                _log.exception("signaling disconnected: %s (%s) — reconnect in %.1fs",
                               exc, type(exc).__name__, backoff)
                self._ws = None
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
