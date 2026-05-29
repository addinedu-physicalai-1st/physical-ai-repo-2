"""D435 depth 와이어 포맷 (eduarm 사본) + 순수 조립 함수.

control_service/streaming/depth_protocol.py 와 **바이트 동일**해야 한다.
ROS 노드는 system python3 에서 돌아 control_service 를 import 못 하므로 vendoring.
두 사본 일치는 tests/test_depth_frame.py 가 강제한다.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import NamedTuple, Optional

import cv2
import numpy as np
import zstandard as zstd

MAGIC_DEPTH = b"DPTH"
DEPTH_PROTO_VERSION = 0x01
DEPTH_HEADER_FMT = "!4sBBBBIQHHHHfffffHHII"
DEPTH_HEADER_SIZE = 60
assert struct.calcsize(DEPTH_HEADER_FMT) == DEPTH_HEADER_SIZE, (
    f"DEPTH_HEADER_FMT mismatch: {struct.calcsize(DEPTH_HEADER_FMT)} != {DEPTH_HEADER_SIZE}"
)

ROBOT_IDS = {"gogoping": 0x01, "eduping": 0x02, "noriarm": 0x03}


class Intr(NamedTuple):
    fx: float
    fy: float
    cx: float
    cy: float


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
    depth_scale: float
    depth_min_mm: int
    depth_max_mm: int
    depth_zstd: bytes
    color_jpeg: bytes


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


def build_depth_frame(
    depth: np.ndarray,
    color: np.ndarray,
    intr: Intr,
    depth_scale: float,
    *,
    robot_id: int,
    frame_seq: int,
    ts_ms: int,
    jpeg_quality: int = 70,
    compressor: Optional[zstd.ZstdCompressor] = None,
) -> DepthFrame:
    """source-agnostic 조립 — (depth uint16, color bgr8, intrinsics) → DepthFrame."""
    if compressor is None:
        compressor = zstd.ZstdCompressor(level=3)
    if depth.dtype != np.uint16:
        depth = depth.astype(np.uint16)
    depth_zstd = compressor.compress(np.ascontiguousarray(depth).tobytes(order="C"))
    ok, jpeg_buf = cv2.imencode(".jpg", color, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not ok:
        raise RuntimeError("cv2.imencode JPEG 실패")
    nonzero = depth[depth > 0]
    dmin = int(nonzero.min()) if nonzero.size else 0
    dmax = int(nonzero.max()) if nonzero.size else 0
    return DepthFrame(
        robot_id=robot_id, frame_seq=frame_seq, ts_ms=ts_ms,
        depth_w=int(depth.shape[1]), depth_h=int(depth.shape[0]),
        color_w=int(color.shape[1]), color_h=int(color.shape[0]),
        fx=float(intr.fx), fy=float(intr.fy), cx=float(intr.cx), cy=float(intr.cy),
        depth_scale=float(depth_scale),
        depth_min_mm=dmin, depth_max_mm=dmax,
        depth_zstd=depth_zstd, color_jpeg=jpeg_buf.tobytes(),
    )
