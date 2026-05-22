"""D435 depth stream 와이어 프로토콜 (laptop streamer → server → robot-web).

영상 MJPEG 파이프라인과 분리: depth 는 uint16 zstd 압축이라 단일 frame 이 ~30-60KB,
UDP 65KB 한계를 종종 넘고 무엇보다 lossy 가 치명적이라 WebSocket binary 채널 사용.

60 B 헤더:
  magic[4s]   = b"DPTH"
  version[B]  = 1
  robot_id[B]
  flags[B]    = 0
  reserved[B] = 0
  frame_seq[I]
  ts_ms[Q]
  depth_w[H], depth_h[H]
  color_w[H], color_h[H]
  fx[f], fy[f], cx[f], cy[f]   # depth camera intrinsics
  depth_scale[f]               # meters per uint16 unit (D435 기본 0.001 = mm)
  depth_min_mm[H], depth_max_mm[H]
  depth_size[I]  # zstd 압축된 uint16 raw bytes 길이
  color_size[I]  # JPEG bytes 길이

payload:
  [depth_size] zstd-compressed uint16 little-endian raw
  [color_size] JPEG (aligned to depth resolution by sensor SDK)

WS 가 TCP 라 CRC 생략. version mismatch / size mismatch 만 검증.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional


MAGIC_DEPTH = b"DPTH"
DEPTH_PROTO_VERSION = 0x01

# !4s + 4*B + I + Q + 4*H + 5*f + 2*H + 2*I = 4+4+4+8+8+20+4+8 = 60
DEPTH_HEADER_FMT = "!4sBBBBIQHHHHfffffHHII"
DEPTH_HEADER_SIZE = 60

assert struct.calcsize(DEPTH_HEADER_FMT) == DEPTH_HEADER_SIZE, (
    f"DEPTH_HEADER_FMT mismatch: {struct.calcsize(DEPTH_HEADER_FMT)} != {DEPTH_HEADER_SIZE}"
)


@dataclass(frozen=True)
class DepthFrame:
    robot_id: int
    frame_seq: int
    ts_ms: int
    depth_w: int
    depth_h: int
    color_w: int
    color_h: int
    fx: float
    fy: float
    cx: float
    cy: float
    depth_scale: float       # meters / unit
    depth_min_mm: int
    depth_max_mm: int
    depth_zstd: bytes        # zstd-compressed uint16 LE depth raster
    color_jpeg: bytes        # JPEG aligned to depth resolution


def encode_depth_frame(frame: DepthFrame) -> bytes:
    header = struct.pack(
        DEPTH_HEADER_FMT,
        MAGIC_DEPTH, DEPTH_PROTO_VERSION,
        frame.robot_id, 0, 0,
        frame.frame_seq, frame.ts_ms,
        frame.depth_w, frame.depth_h,
        frame.color_w, frame.color_h,
        frame.fx, frame.fy, frame.cx, frame.cy, frame.depth_scale,
        frame.depth_min_mm, frame.depth_max_mm,
        len(frame.depth_zstd), len(frame.color_jpeg),
    )
    return header + frame.depth_zstd + frame.color_jpeg


def decode_depth_frame(data: bytes) -> Optional[DepthFrame]:
    """Binary frame → DepthFrame. 검증 실패 시 None."""
    if len(data) < DEPTH_HEADER_SIZE:
        return None
    try:
        (
            magic, ver, robot_id, _flags, _reserved,
            frame_seq, ts_ms,
            depth_w, depth_h, color_w, color_h,
            fx, fy, cx, cy, depth_scale,
            depth_min, depth_max,
            depth_size, color_size,
        ) = struct.unpack(DEPTH_HEADER_FMT, data[:DEPTH_HEADER_SIZE])
    except struct.error:
        return None
    if magic != MAGIC_DEPTH or ver != DEPTH_PROTO_VERSION:
        return None
    expected_len = DEPTH_HEADER_SIZE + depth_size + color_size
    if expected_len != len(data):
        return None
    depth_bytes = data[DEPTH_HEADER_SIZE:DEPTH_HEADER_SIZE + depth_size]
    color_bytes = data[DEPTH_HEADER_SIZE + depth_size:]
    return DepthFrame(
        robot_id=robot_id, frame_seq=frame_seq, ts_ms=ts_ms,
        depth_w=depth_w, depth_h=depth_h,
        color_w=color_w, color_h=color_h,
        fx=fx, fy=fy, cx=cx, cy=cy,
        depth_scale=depth_scale,
        depth_min_mm=depth_min, depth_max_mm=depth_max,
        depth_zstd=depth_bytes, color_jpeg=color_bytes,
    )
