"""service/control-service/control_service/streaming/depth_*.py 단위 테스트.

depth_protocol: encode/decode round-trip + 검증 실패 경로.
depth_hub:      subscribe / publish fan-out / drop-oldest / latest-on-subscribe.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from control_service.streaming.depth_hub import DepthHub
from control_service.streaming.depth_protocol import (
    DEPTH_HEADER_SIZE, DepthFrame,
    decode_depth_frame, encode_depth_frame,
)


def _make_frame(
    robot_id: int = 2,
    frame_seq: int = 1,
    depth: bytes = b"\x00" * 16,
    color: bytes = b"\xff\xd8\xff",   # JPEG SOI 흉내
) -> DepthFrame:
    return DepthFrame(
        robot_id=robot_id, frame_seq=frame_seq, ts_ms=12345,
        depth_w=320, depth_h=240, color_w=320, color_h=240,
        fx=200.0, fy=200.0, cx=160.0, cy=120.0,
        depth_scale=0.001,
        depth_min_mm=300, depth_max_mm=4000,
        depth_zstd=depth, color_jpeg=color,
    )


# ----- protocol -----


def test_encode_decode_round_trip() -> None:
    f = _make_frame(depth=b"hello", color=b"world")
    raw = encode_depth_frame(f)
    assert len(raw) == DEPTH_HEADER_SIZE + len(b"hello") + len(b"world")
    out = decode_depth_frame(raw)
    assert out is not None
    # float32 round-trip — 정확 비교 대신 tolerance
    assert out.robot_id == f.robot_id
    assert out.frame_seq == f.frame_seq
    assert out.ts_ms == f.ts_ms
    assert out.depth_w == f.depth_w
    assert out.depth_h == f.depth_h
    assert out.color_w == f.color_w
    assert out.color_h == f.color_h
    assert out.fx == pytest.approx(f.fx, rel=1e-6)
    assert out.fy == pytest.approx(f.fy, rel=1e-6)
    assert out.cx == pytest.approx(f.cx, rel=1e-6)
    assert out.cy == pytest.approx(f.cy, rel=1e-6)
    assert out.depth_scale == pytest.approx(f.depth_scale, rel=1e-6)
    assert out.depth_min_mm == f.depth_min_mm
    assert out.depth_max_mm == f.depth_max_mm
    assert out.depth_zstd == f.depth_zstd
    assert out.color_jpeg == f.color_jpeg


def test_decode_rejects_short_buffer() -> None:
    assert decode_depth_frame(b"") is None
    assert decode_depth_frame(b"\x00" * (DEPTH_HEADER_SIZE - 1)) is None


def test_decode_rejects_bad_magic() -> None:
    f = _make_frame()
    raw = bytearray(encode_depth_frame(f))
    raw[0] = ord("X")   # magic 첫 바이트 깨뜨림
    assert decode_depth_frame(bytes(raw)) is None


def test_decode_rejects_size_mismatch() -> None:
    f = _make_frame(depth=b"abc", color=b"xy")
    raw = encode_depth_frame(f)
    # 마지막 바이트 잘라서 size mismatch
    assert decode_depth_frame(raw[:-1]) is None


def test_decode_rejects_version_mismatch() -> None:
    f = _make_frame()
    raw = bytearray(encode_depth_frame(f))
    raw[4] = 0x99   # version byte
    assert decode_depth_frame(bytes(raw)) is None


# ----- hub -----


@dataclass
class _FakeClient:
    send_queue: asyncio.Queue
    subscriptions: set = field(default_factory=set)


def _client(maxsize: int = 8) -> _FakeClient:
    return _FakeClient(send_queue=asyncio.Queue(maxsize=maxsize))


def test_publish_with_no_subscribers_keeps_latest() -> None:
    hub = DepthHub()
    f = _make_frame(frame_seq=42)
    hub.publish(f)
    assert hub.subscriber_count(f.robot_id) == 0
    assert hub.latest_seq(f.robot_id) == 42


def test_new_subscriber_gets_latest_frame() -> None:
    hub = DepthHub()
    hub.publish(_make_frame(frame_seq=7))
    c = _client()
    assert hub.subscribe(c, robot_id=2) is True
    assert c.send_queue.qsize() == 1
    f = c.send_queue.get_nowait()
    assert f.frame_seq == 7


def test_publish_fans_out_to_subscribers() -> None:
    hub = DepthHub()
    c1 = _client()
    c2 = _client()
    hub.subscribe(c1, 2)
    hub.subscribe(c2, 2)
    hub.publish(_make_frame(frame_seq=1))
    assert c1.send_queue.qsize() == 1
    assert c2.send_queue.qsize() == 1


def test_subscribe_only_target_robot() -> None:
    hub = DepthHub()
    c = _client()
    hub.subscribe(c, 2)   # eduping
    hub.publish(_make_frame(robot_id=1, frame_seq=1))   # gogoping
    assert c.send_queue.qsize() == 0


def test_full_queue_drops_oldest() -> None:
    hub = DepthHub()
    c = _client(maxsize=1)
    hub.subscribe(c, 2)
    # latest-on-subscribe 부재 — 새 frame 만 들어옴
    hub.publish(_make_frame(frame_seq=1))
    hub.publish(_make_frame(frame_seq=2))
    hub.publish(_make_frame(frame_seq=3))
    assert c.send_queue.qsize() == 1
    last = c.send_queue.get_nowait()
    assert last.frame_seq == 3


def test_unsubscribe_stops_delivery() -> None:
    hub = DepthHub()
    c = _client()
    hub.subscribe(c, 2)
    hub.publish(_make_frame(frame_seq=1))
    c.send_queue.get_nowait()
    hub.unsubscribe(c, 2)
    hub.publish(_make_frame(frame_seq=2))
    assert c.send_queue.qsize() == 0


def test_subscribe_idempotent() -> None:
    hub = DepthHub()
    c = _client()
    assert hub.subscribe(c, 2) is True
    assert hub.subscribe(c, 2) is False


def test_unsubscribe_all_clears_depth_only() -> None:
    """video subscription tuple 과 depth subscription tuple 이 같은 set 에 들어가도
    depth hub 는 자기 stream_id sentinel 만 정리해야 함."""
    hub = DepthHub()
    c = _client()
    # video 가 직접 (robot, 0) 을 추가했다고 가정
    c.subscriptions.add((2, 0))
    hub.subscribe(c, 2)
    assert (2, 0) in c.subscriptions
    hub.unsubscribe_all(c)
    # depth 만 빠지고 video 는 남아있어야 함
    assert (2, 0) in c.subscriptions
    assert (2, -1) not in c.subscriptions
