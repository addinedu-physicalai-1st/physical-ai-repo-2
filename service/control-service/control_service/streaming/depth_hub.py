"""Depth frame fan-out hub (DepthFrame → subscribed consumer WS clients).

영상 FrameHub 와 분리: depth 는 (robot_id) 만 키로 사용 (stream_id 개념 없음 — 로봇당 하나).
저장: latest_frame_per_robot — 새 consumer 가 붙으면 즉시 1 frame 보내서 빈 화면 회피.
드롭 정책: 큐 full 이면 가장 오래된 frame drop.

영상 hub 와 마찬가지로 asyncio 단일 thread 에서만 호출 → lock 없음.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from control_service.streaming.depth_protocol import DepthFrame

if TYPE_CHECKING:
    from control_service.streaming.client_registry import WSClient


_log = logging.getLogger("streaming.depth_hub")


class DepthHub:
    def __init__(self) -> None:
        self._subs: dict[int, list["WSClient"]] = defaultdict(list)
        self._latest: dict[int, DepthFrame] = {}

    def subscribe(self, client: "WSClient", robot_id: int) -> bool:
        """Returns True 면 새 구독 등록, False 면 이미 구독중. 등록 시 latest frame 즉시 push."""
        key = (robot_id, _DEPTH_STREAM_ID)
        if key in client.subscriptions:
            return False
        self._subs[robot_id].append(client)
        client.subscriptions.add(key)
        latest = self._latest.get(robot_id)
        if latest is not None:
            self._enqueue(client, latest)
        return True

    def unsubscribe(self, client: "WSClient", robot_id: int) -> bool:
        key = (robot_id, _DEPTH_STREAM_ID)
        if key not in client.subscriptions:
            return False
        client.subscriptions.discard(key)
        try:
            self._subs[robot_id].remove(client)
        except (ValueError, KeyError):
            pass
        if not self._subs.get(robot_id):
            self._subs.pop(robot_id, None)
        return True

    def unsubscribe_all(self, client: "WSClient") -> None:
        for (rid, sid) in list(client.subscriptions):
            if sid == _DEPTH_STREAM_ID:
                self.unsubscribe(client, rid)

    def publish(self, frame: DepthFrame) -> None:
        """Producer WS 가 frame 도착 시 호출. 구독자 모두에게 fan-out + latest 갱신."""
        self._latest[frame.robot_id] = frame
        clients = self._subs.get(frame.robot_id)
        if not clients:
            return
        for client in clients:
            self._enqueue(client, frame)

    def subscriber_count(self, robot_id: int) -> int:
        return len(self._subs.get(robot_id, []))

    def snapshot_counts(self) -> dict[int, int]:
        return {rid: len(clients) for rid, clients in self._subs.items()}

    def latest_seq(self, robot_id: int) -> int | None:
        latest = self._latest.get(robot_id)
        return None if latest is None else latest.frame_seq

    @staticmethod
    def _enqueue(client: "WSClient", frame: DepthFrame) -> None:
        q = client.send_queue
        if q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            q.put_nowait(frame)
        except asyncio.QueueFull:
            pass


# WSClient.subscriptions 는 (robot_id, stream_id) tuple 이라 video hub 와 키 충돌 회피.
# depth 는 stream_id 자리에 sentinel -1 사용.
_DEPTH_STREAM_ID = -1
