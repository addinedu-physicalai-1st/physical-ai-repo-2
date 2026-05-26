"""WebRTC signaling — doctor portal ↔ eduping robot-web SDP/ICE relay.

P2P 미디어 채널 (cam + mic) 의 시작 절차만 담당. 일단 양쪽이 한 명씩만 접속하는
시나리오 (1 doctor ↔ 1 eduping) 고정 — 멀티 룸 지원은 추후.

흐름:
    [Doctor 브라우저]                            [EduPing 브라우저]
       WS /ws/doctor/signal?role=doctor      WS /ws/doctor/signal?role=eduping
              │                                      │
              └─────── control-service ──────────────┘
                    한쪽 msg 받으면 반대편으로 forward

메시지 (JSON):
    { "type": "offer",  "sdp": "..."  }
    { "type": "answer", "sdp": "..."  }
    { "type": "ice",    "candidate": {...} | null }
    { "type": "peer",   "present": bool }   ← 서버가 보냄 (peer join/leave 알림)

순서:
    1. 양쪽 모두 connect.
    2. 두 번째 peer 가 들어오면 서버가 양쪽에 {type:peer, present:true} 보냄.
    3. doctor 가 offer 만들고 send.
    4. eduping 이 answer 만들고 reply.
    5. 양쪽이 ICE candidate 교환.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

log = logging.getLogger(__name__)

ROLES = ("doctor", "eduping")


class SignalingHub:
    """양쪽 한 명씩 보관. 한쪽 메시지를 반대편으로 그대로 forward."""

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
        log.info("signaling %s registered (peers=%s)", role, list(self._peers))
        # peer presence 알림.
        await self._broadcast_presence()

    async def unregister(self, role: str, ws: WebSocket) -> None:
        if self._peers.get(role) is ws:
            del self._peers[role]
            log.info("signaling %s gone", role)
            await self._broadcast_presence()

    async def _broadcast_presence(self) -> None:
        for role, ws in list(self._peers.items()):
            other = "eduping" if role == "doctor" else "doctor"
            payload = json.dumps({"type": "peer", "present": other in self._peers})
            try:
                await ws.send_text(payload)
            except Exception:
                pass

    async def forward(self, from_role: str, message: str) -> None:
        other = "eduping" if from_role == "doctor" else "doctor"
        peer = self._peers.get(other)
        if peer is None:
            return
        try:
            await peer.send_text(message)
        except Exception as e:
            log.warning("forward to %s failed: %s", other, e)


def build_router(hub: SignalingHub) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws/doctor/signal")
    async def ws_handler(  # noqa: ANN202
        ws: WebSocket,
        role: str | None = Query(default=None),
    ) -> None:
        if role not in ROLES:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.accept()
        try:
            await hub.register(role, ws)
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                text = msg.get("text")
                if text:
                    await hub.forward(role, text)
        except WebSocketDisconnect:
            pass
        finally:
            await hub.unregister(role, ws)

    return r
