"""subscriber 0 시 frame drop 검증 (PLAN §1.5 server-side filter).

별도 파일로 분리 — drop 동작이 SR-CAM-002 의 핵심 비기능 요구.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from server.control.streaming.frame_hub import FrameHub
from server.control.streaming.protocol import VideoPacket


@dataclass
class _FakeClient:
    send_queue: asyncio.Queue
    subscriptions: set = field(default_factory=set)


def _packet(robot_id: int = 1, stream_id: int = 0) -> VideoPacket:
    return VideoPacket(
        robot_id=robot_id, stream_id=stream_id,
        frame_seq=0, ts_ms=0, jpeg=b"x",
    )


def test_publish_with_zero_subscribers_does_nothing() -> None:
    """subscriber 0 → publish 즉시 return, 부작용 없음."""
    hub = FrameHub()
    # 예외 없이 100회 publish 가능 (CPU 부하 0)
    for _ in range(100):
        hub.publish(_packet())
    # 내부 dict 에 빈 entry 가 쌓이지 않음
    assert len(hub._subs) == 0


def test_publish_after_unsubscribe_drops() -> None:
    hub = FrameHub()
    c = _FakeClient(send_queue=asyncio.Queue(maxsize=8))
    hub.subscribe(c, 1, 0)
    hub.publish(_packet())
    assert c.send_queue.qsize() == 1
    c.send_queue.get_nowait()

    hub.unsubscribe(c, 1, 0)
    hub.publish(_packet())
    assert c.send_queue.qsize() == 0


def test_publish_to_unrelated_topic_drops() -> None:
    hub = FrameHub()
    c = _FakeClient(send_queue=asyncio.Queue(maxsize=8))
    hub.subscribe(c, 1, 0)   # gogoping/0 만 구독

    hub.publish(_packet(robot_id=2))   # eduping → drop
    hub.publish(_packet(robot_id=3))   # noriarm → drop
    hub.publish(_packet(robot_id=1, stream_id=1))   # gogoping/1 도 drop

    assert c.send_queue.qsize() == 0

    # 매칭되는 토픽만 도착
    hub.publish(_packet(robot_id=1, stream_id=0))
    assert c.send_queue.qsize() == 1


def test_subscribe_then_unsubscribe_then_resubscribe() -> None:
    """sub → unsub → resub 사이클 — 큐 새로 받음 (재연결 시나리오)."""
    hub = FrameHub()
    c = _FakeClient(send_queue=asyncio.Queue(maxsize=8))

    hub.subscribe(c, 1, 0)
    hub.publish(_packet())
    assert c.send_queue.qsize() == 1
    c.send_queue.get_nowait()

    hub.unsubscribe(c, 1, 0)
    # drop 단계
    for _ in range(5):
        hub.publish(_packet())
    assert c.send_queue.qsize() == 0

    hub.subscribe(c, 1, 0)
    hub.publish(_packet())
    assert c.send_queue.qsize() == 1
