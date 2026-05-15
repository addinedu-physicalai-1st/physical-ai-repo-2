"""service/control-service/control_service/streaming/protocol.py 단위 테스트.

PLAN §5.1, §5.2, §5.3 명세 검증.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from control_service.streaming.protocol import (
    ACTION_START,
    ACTION_STOP,
    CTRL_HEADER_FMT,
    CTRL_HEADER_SIZE,
    HelloMsg,
    MAGIC_CTRL,
    MAGIC_PING,
    PROTO_VERSION,
    SubscribeMsg,
    UnsubscribeMsg,
    VIDEO_HEADER_FMT,
    VIDEO_HEADER_SIZE,
    WS_FRAME_HEADER_FMT,
    WS_FRAME_HEADER_SIZE,
    WS_MSG_VIDEO_FRAME,
    encode_ctrl_packet,
    encode_ws_frame,
    parse_video_packet,
)


# --------------------------------------------------------- 헤더 크기 명세


def test_video_header_size_is_28() -> None:
    assert VIDEO_HEADER_SIZE == 28
    assert struct.calcsize(VIDEO_HEADER_FMT) == 28


def test_ctrl_header_size_is_12() -> None:
    assert CTRL_HEADER_SIZE == 12
    assert struct.calcsize(CTRL_HEADER_FMT) == 12


def test_ws_frame_header_size_is_20() -> None:
    assert WS_FRAME_HEADER_SIZE == 20
    assert struct.calcsize(WS_FRAME_HEADER_FMT) == 20


# --------------------------------------------------------- video packet


def _make_video_packet(
    robot_id: int = 1, stream_id: int = 0, seq: int = 42, jpeg: bytes = b"jpegdata",
) -> bytes:
    crc = zlib.crc32(jpeg) & 0xFFFFFFFF
    header = struct.pack(
        VIDEO_HEADER_FMT,
        MAGIC_PING, PROTO_VERSION,
        robot_id, stream_id, 0,
        seq, 1234567890, len(jpeg), crc,
    )
    return header + jpeg


def test_parse_video_packet_round_trip() -> None:
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"
    data = _make_video_packet(robot_id=2, stream_id=3, seq=999, jpeg=jpeg)
    packet = parse_video_packet(data)
    assert packet is not None
    assert packet.robot_id == 2
    assert packet.stream_id == 3
    assert packet.frame_seq == 999
    assert packet.ts_ms == 1234567890
    assert packet.jpeg == jpeg


def test_parse_video_packet_bad_magic_drops() -> None:
    data = _make_video_packet()
    bad = b"XXXX" + data[4:]
    assert parse_video_packet(bad) is None


def test_parse_video_packet_bad_version_drops() -> None:
    data = _make_video_packet()
    # version 바이트만 0x99 로
    bad = data[:4] + b"\x99" + data[5:]
    assert parse_video_packet(bad) is None


def test_parse_video_packet_size_mismatch_drops() -> None:
    """jpeg_size 헤더 vs 실제 길이 불일치 → drop (단편화 손실 등)."""
    data = _make_video_packet()
    # 마지막 바이트 잘라냄
    truncated = data[:-1]
    assert parse_video_packet(truncated) is None


def test_parse_video_packet_crc_corruption_drops() -> None:
    data = _make_video_packet()
    # JPEG payload 안의 1바이트 변조
    corrupted = bytearray(data)
    corrupted[VIDEO_HEADER_SIZE + 5] ^= 0xFF
    assert parse_video_packet(bytes(corrupted)) is None


def test_parse_video_packet_too_short_drops() -> None:
    assert parse_video_packet(b"") is None
    assert parse_video_packet(b"PING") is None
    assert parse_video_packet(b"\x00" * (VIDEO_HEADER_SIZE - 1)) is None


# --------------------------------------------------------- ctrl packet


def test_encode_ctrl_packet_start() -> None:
    pkt = encode_ctrl_packet(ACTION_START, intent_seq=1)
    assert len(pkt) == CTRL_HEADER_SIZE
    magic, ver, action, _resv, seq = struct.unpack(CTRL_HEADER_FMT, pkt)
    assert magic == MAGIC_CTRL
    assert ver == PROTO_VERSION
    assert action == ACTION_START
    assert seq == 1


def test_encode_ctrl_packet_stop_with_seq() -> None:
    pkt = encode_ctrl_packet(ACTION_STOP, intent_seq=42)
    _, _, action, _, seq = struct.unpack(CTRL_HEADER_FMT, pkt)
    assert action == ACTION_STOP
    assert seq == 42


# --------------------------------------------------------- ws binary frame


def test_encode_ws_frame_layout() -> None:
    jpeg = b"hello jpeg payload"
    data = _make_video_packet(robot_id=1, stream_id=0, seq=7, jpeg=jpeg)
    packet = parse_video_packet(data)
    assert packet is not None

    ws_bytes = encode_ws_frame(packet)
    assert len(ws_bytes) == WS_FRAME_HEADER_SIZE + len(jpeg)
    msg_type = ws_bytes[0]
    robot_id = ws_bytes[1]
    stream_id = ws_bytes[2]
    assert msg_type == WS_MSG_VIDEO_FRAME
    assert robot_id == 1
    assert stream_id == 0
    assert ws_bytes[WS_FRAME_HEADER_SIZE:] == jpeg


# --------------------------------------------------------- pydantic 메시지


def test_hello_msg_validates() -> None:
    m = HelloMsg(type="hello", client_id="abc", client_kind="admin", ts_ms=1)
    assert m.client_id == "abc"


def test_subscribe_msg_default_stream_zero() -> None:
    m = SubscribeMsg(type="subscribe", robot="gogoping", ts_ms=1)
    assert m.stream == 0


def test_subscribe_msg_stream_range_validated() -> None:
    with pytest.raises(Exception):
        SubscribeMsg(type="subscribe", robot="gogoping", stream=8, ts_ms=1)
    with pytest.raises(Exception):
        SubscribeMsg(type="subscribe", robot="gogoping", stream=-1, ts_ms=1)


def test_subscribe_msg_invalid_robot_rejected() -> None:
    with pytest.raises(Exception):
        SubscribeMsg(type="subscribe", robot="not-a-robot", ts_ms=1)


def test_unsubscribe_msg_validates() -> None:
    m = UnsubscribeMsg(type="unsubscribe", robot="eduping", stream=2, ts_ms=1)
    assert m.robot == "eduping"
    assert m.stream == 2
