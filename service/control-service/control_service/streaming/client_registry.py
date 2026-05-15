"""WS 클라이언트 관리 + heartbeat.

PLAN §6, §5.3 (heartbeat 30s tick / 60s timeout).
asyncio 단일 thread 에서만 호출 → lock 불필요.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from fastapi import WebSocket


@dataclass
class WSClient:
    """단일 WS 연결 상태.

    send_queue 는 frame_hub 가 publish 한 packet 을 저장하는 fan-in 큐.
    여러 (robot_id, stream_id) 가 한 큐에 섞여 도착, send_loop 가 ws.send_bytes.
    """
    client_id: str
    client_kind: str
    ws: WebSocket
    send_queue: asyncio.Queue
    subscriptions: set[tuple[int, int]] = field(default_factory=set)
    last_pong_at: float = field(default_factory=time.monotonic)
    user_id: str | None = None


class ClientRegistry:
    """client_id → WSClient 인덱스."""

    def __init__(self) -> None:
        self._clients: dict[str, WSClient] = {}

    def add(self, client: WSClient) -> None:
        self._clients[client.client_id] = client

    def remove(self, client_id: str) -> WSClient | None:
        return self._clients.pop(client_id, None)

    def get(self, client_id: str) -> WSClient | None:
        return self._clients.get(client_id)

    def all(self) -> list[WSClient]:
        return list(self._clients.values())

    def count(self) -> int:
        return len(self._clients)
