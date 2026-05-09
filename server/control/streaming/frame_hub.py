"""asyncio 측 frame fan-out hub.

PLAN §6 (스레드 모델), §1.5 (subscriber 0 → drop server-side filter).

UdpFrameReceiver thread 가 `loop.call_soon_threadsafe(hub.publish, packet)` 로 호출.
Subscribe/unsubscribe 는 WS 핸들러 (asyncio) 에서 호출.
모든 메서드는 asyncio 단일 thread 에서만 실행되므로 lock 불필요.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from server.control.streaming.protocol import VideoPacket

if TYPE_CHECKING:
    from server.control.streaming.client_registry import WSClient


_log = logging.getLogger("streaming.hub")


class FrameHub:
    """(robot_id, stream_id) → 구독 client 리스트 라우팅.

    publish 시 subscribe 한 client 의 send_queue 에 push.
    queue 가득 차면 drop-oldest 정책.
    구독자 0 명이면 publish 즉시 drop (PLAN §1.5).
    """

    def __init__(self) -> None:
        self._subs: dict[tuple[int, int], list["WSClient"]] = defaultdict(list)

    def subscribe(self, client: "WSClient", robot_id: int, stream_id: int) -> bool:
        """client 의 (robot, stream) 구독 등록. 이미 구독 중이면 False."""
        key = (robot_id, stream_id)
        if key in client.subscriptions:
            return False
        self._subs[key].append(client)
        client.subscriptions.add(key)
        return True

    def unsubscribe(self, client: "WSClient", robot_id: int, stream_id: int) -> bool:
        """client 의 (robot, stream) 구독 해제. 미구독이면 False."""
        key = (robot_id, stream_id)
        if key not in client.subscriptions:
            return False
        client.subscriptions.discard(key)
        try:
            self._subs[key].remove(client)
        except (ValueError, KeyError):
            pass
        if not self._subs.get(key):
            self._subs.pop(key, None)
        return True

    def unsubscribe_all(self, client: "WSClient") -> None:
        """client 의 모든 구독 해제 (disconnect 시)."""
        for key in list(client.subscriptions):
            self.unsubscribe(client, key[0], key[1])

    def publish(self, packet: VideoPacket) -> None:
        """UDP 수신 thread 가 call_soon_threadsafe 로 호출.

        구독자별 send_queue 에 push. 가득 차면 가장 오래된 frame drop.
        구독자 0 명이면 즉시 return (drop, PLAN §1.5).
        """
        clients = self._subs.get((packet.robot_id, packet.stream_id))
        if not clients:
            return
        for client in clients:
            q = client.send_queue
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait(packet)
            except asyncio.QueueFull:
                pass

    def subscriber_count(self, robot_id: int, stream_id: int) -> int:
        return len(self._subs.get((robot_id, stream_id), []))

    def snapshot_counts(self) -> dict[tuple[int, int], int]:
        return {k: len(v) for k, v in self._subs.items()}
