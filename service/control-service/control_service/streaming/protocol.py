"""스트리밍 와이어 프로토콜.

PLAN §5.1 (UDP 영상 28B 헤더), §5.2 (UDP 제어 12B), §5.3 (WS binary 20B + JSON).
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field


PROTO_VERSION = 0x01


# =============================================================================
# UDP 영상 패킷 (Pi → Server)  PLAN §5.1
# =============================================================================
# magic[4s] + version[B] + robot_id[B] + stream_id[B] + flags[B]
# + frame_seq[I] + ts_ms[Q] + jpeg_size[I] + crc32[I]
VIDEO_HEADER_FMT = "!4sBBBBIQII"
VIDEO_HEADER_SIZE = 28
MAGIC_PING = b"PING"

assert struct.calcsize(VIDEO_HEADER_FMT) == VIDEO_HEADER_SIZE


@dataclass
class VideoPacket:
    robot_id: int
    stream_id: int
    frame_seq: int
    ts_ms: int
    jpeg: bytes


def parse_video_packet(data: bytes) -> Optional[VideoPacket]:
    """UDP 데이터그램 → VideoPacket. 검증 실패 시 None.

    검증 (PLAN §5.1):
      1. 길이 ≥ 28B
      2. magic == "PING", version == 1
      3. jpeg_size + 28 == len(data)
      4. crc32(jpeg) == 헤더 crc
    """
    if len(data) < VIDEO_HEADER_SIZE:
        return None
    try:
        magic, ver, robot_id, stream_id, _flags, seq, ts_ms, size, crc = struct.unpack(
            VIDEO_HEADER_FMT, data[:VIDEO_HEADER_SIZE],
        )
    except struct.error:
        return None
    if magic != MAGIC_PING or ver != PROTO_VERSION:
        return None
    if size != len(data) - VIDEO_HEADER_SIZE:
        return None
    jpeg = data[VIDEO_HEADER_SIZE:VIDEO_HEADER_SIZE + size]
    if (zlib.crc32(jpeg) & 0xFFFFFFFF) != crc:
        return None
    return VideoPacket(
        robot_id=robot_id, stream_id=stream_id,
        frame_seq=seq, ts_ms=ts_ms, jpeg=jpeg,
    )


# =============================================================================
# UDP 제어 패킷 (Server → Pi)  PLAN §5.2
# =============================================================================
# magic[4s] + version[B] + action[B] + reserved[H] + intent_seq[I]
CTRL_HEADER_FMT = "!4sBBHI"
CTRL_HEADER_SIZE = 12
MAGIC_CTRL = b"CTRL"
ACTION_START = 0x01
ACTION_STOP = 0x02

assert struct.calcsize(CTRL_HEADER_FMT) == CTRL_HEADER_SIZE


def encode_ctrl_packet(action: int, intent_seq: int) -> bytes:
    """제어 패킷 직렬화."""
    return struct.pack(
        CTRL_HEADER_FMT, MAGIC_CTRL, PROTO_VERSION, action, 0, intent_seq,
    )


# =============================================================================
# WS Binary frame (Server → Client)  PLAN §5.3
# =============================================================================
# msg_type[B] + robot_id[B] + stream_id[B] + reserved[B]
# + frame_seq[I] + ts_ms[Q] + jpeg_size[I]
WS_FRAME_HEADER_FMT = "!BBBBIQI"
WS_FRAME_HEADER_SIZE = 20
WS_MSG_VIDEO_FRAME = 0x10

assert struct.calcsize(WS_FRAME_HEADER_FMT) == WS_FRAME_HEADER_SIZE


def encode_ws_frame(packet: VideoPacket) -> bytes:
    """VideoPacket → WS binary 메시지."""
    header = struct.pack(
        WS_FRAME_HEADER_FMT,
        WS_MSG_VIDEO_FRAME, packet.robot_id, packet.stream_id, 0,
        packet.frame_seq, packet.ts_ms, len(packet.jpeg),
    )
    return header + packet.jpeg


# =============================================================================
# WS JSON 메시지 (Pydantic)  PLAN §5.3
# =============================================================================

RobotName = Literal["gogoping", "eduping", "noriarm"]


class HelloMsg(BaseModel):
    type: Literal["hello"]
    client_id: str = Field(min_length=1, max_length=128)
    client_kind: str = Field(min_length=1, max_length=32)
    ts_ms: int


class SubscribeMsg(BaseModel):
    type: Literal["subscribe"]
    robot: RobotName
    stream: int = Field(default=0, ge=0, le=7)
    ts_ms: int


class UnsubscribeMsg(BaseModel):
    type: Literal["unsubscribe"]
    robot: RobotName
    stream: int = Field(default=0, ge=0, le=7)
    ts_ms: int


class PongMsg(BaseModel):
    type: Literal["pong"]
    ts_ms: int
