"""server/control/streaming/frame_hub.py 단위 테스트.

PLAN §1.5 (server-side filter), §6 (drop-oldest), §3.4 (multi-subscribe).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from server.control.streaming.frame_hub import FrameHub
from server.control.streaming.protocol import VideoPacket


def _make_packet(robot_id: int = 1, stream_id: int = 0, seq: int = 0) -> VideoPacket:
    return VideoPacket(
        robot_id=robot_id, stream_id=stream_id,
        frame_seq=seq, ts_ms=0, jpeg=b"jpeg",
    )


@dataclass
class _FakeClient:
    """WSClient 의 최소 인터페이스 — send_queue + subscriptions 만 가짐."""
    send_queue: asyncio.Queue
    subscriptions: set = field(default_factory=set)


@pytest.fixture
def hub() -> FrameHub:
    return FrameHub()


@pytest.fixture
def client_factory():
    def _make(maxsize: int = 8) -> _FakeClient:
        return _FakeClient(send_queue=asyncio.Queue(maxsize=maxsize))
    return _make


# ------------------------------------------------- subscriber 0 → drop


def test_publish_with_no_subscribers_drops(hub: FrameHub) -> None:
    """SR-CAM-002 server-side filter — subscriber 0 이면 즉시 return."""
    packet = _make_packet()
    hub.publish(packet)   # 예외 없이 무동작


def test_publish_only_to_matching_subscribers(hub: FrameHub, client_factory) -> None:
    c1 = client_factory()
    c2 = client_factory()
    hub.subscribe(c1, robot_id=1, stream_id=0)   # gogoping/0
    hub.subscribe(c2, robot_id=2, stream_id=0)   # eduping/0

    hub.publish(_make_packet(robot_id=1, stream_id=0))

    assert c1.send_queue.qsize() == 1
    assert c2.send_queue.qsize() == 0


# ------------------------------------------------- multi-subscribe


def test_one_client_subscribes_multiple_topics(hub: FrameHub, client_factory) -> None:
    c = client_factory()
    hub.subscribe(c, 1, 0)
    hub.subscribe(c, 2, 0)
    hub.subscribe(c, 3, 0)

    assert (1, 0) in c.subscriptions
    assert (2, 0) in c.subscriptions
    assert (3, 0) in c.subscriptions

    hub.publish(_make_packet(robot_id=1))
    hub.publish(_make_packet(robot_id=2))
    hub.publish(_make_packet(robot_id=3))

    # 같은 send_queue 에 3개 모두 도착
    assert c.send_queue.qsize() == 3


def test_subscribe_idempotent(hub: FrameHub, client_factory) -> None:
    c = client_factory()
    assert hub.subscribe(c, 1, 0) is True
    assert hub.subscribe(c, 1, 0) is False   # 이미 구독 중
    # 한 frame 만 들어가야 함
    hub.publish(_make_packet(robot_id=1))
    assert c.send_queue.qsize() == 1


# ------------------------------------------------- multi-client fan-out


def test_publish_fans_out_to_multiple_clients(hub: FrameHub, client_factory) -> None:
    clients = [client_factory() for _ in range(3)]
    for c in clients:
        hub.subscribe(c, 1, 0)

    hub.publish(_make_packet(robot_id=1))

    for c in clients:
        assert c.send_queue.qsize() == 1


# ------------------------------------------------- drop-oldest 정책


def test_full_queue_drops_oldest(hub: FrameHub, client_factory) -> None:
    """maxsize=1 큐가 가득 차면 가장 오래된 frame 을 drop 후 새 frame 삽입."""
    c = client_factory(maxsize=1)
    hub.subscribe(c, 1, 0)

    p1 = _make_packet(robot_id=1, seq=1)
    p2 = _make_packet(robot_id=1, seq=2)
    p3 = _make_packet(robot_id=1, seq=3)

    hub.publish(p1)
    hub.publish(p2)
    hub.publish(p3)

    # 큐엔 가장 최근 (p3) 만 남아야 함
    assert c.send_queue.qsize() == 1
    last = c.send_queue.get_nowait()
    assert last.frame_seq == 3


# ------------------------------------------------- unsubscribe


def test_unsubscribe_stops_delivery(hub: FrameHub, client_factory) -> None:
    c = client_factory()
    hub.subscribe(c, 1, 0)
    hub.publish(_make_packet(robot_id=1))
    assert c.send_queue.qsize() == 1
    c.send_queue.get_nowait()

    hub.unsubscribe(c, 1, 0)
    hub.publish(_make_packet(robot_id=1))
    assert c.send_queue.qsize() == 0


def test_unsubscribe_unknown_returns_false(hub: FrameHub, client_factory) -> None:
    c = client_factory()
    assert hub.unsubscribe(c, 1, 0) is False


def test_unsubscribe_all_clears_all_topics(hub: FrameHub, client_factory) -> None:
    c = client_factory()
    hub.subscribe(c, 1, 0)
    hub.subscribe(c, 2, 0)
    hub.subscribe(c, 3, 0)
    assert len(c.subscriptions) == 3

    hub.unsubscribe_all(c)

    assert len(c.subscriptions) == 0
    # 이후 publish 도착하지 않음
    for rid in (1, 2, 3):
        hub.publish(_make_packet(robot_id=rid))
    assert c.send_queue.qsize() == 0


def test_unsubscribe_one_client_keeps_others(hub: FrameHub, client_factory) -> None:
    c1 = client_factory()
    c2 = client_factory()
    hub.subscribe(c1, 1, 0)
    hub.subscribe(c2, 1, 0)

    hub.unsubscribe(c1, 1, 0)
    hub.publish(_make_packet(robot_id=1))

    assert c1.send_queue.qsize() == 0
    assert c2.send_queue.qsize() == 1


# ------------------------------------------------- subscriber_count / snapshot


def test_subscriber_count_tracks_changes(hub: FrameHub, client_factory) -> None:
    c1 = client_factory()
    c2 = client_factory()
    assert hub.subscriber_count(1, 0) == 0
    hub.subscribe(c1, 1, 0)
    assert hub.subscriber_count(1, 0) == 1
    hub.subscribe(c2, 1, 0)
    assert hub.subscriber_count(1, 0) == 2
    hub.unsubscribe(c1, 1, 0)
    assert hub.subscriber_count(1, 0) == 1


def test_snapshot_counts(hub: FrameHub, client_factory) -> None:
    c = client_factory()
    hub.subscribe(c, 1, 0)
    hub.subscribe(c, 2, 0)
    snap = hub.snapshot_counts()
    assert snap[(1, 0)] == 1
    assert snap[(2, 0)] == 1
