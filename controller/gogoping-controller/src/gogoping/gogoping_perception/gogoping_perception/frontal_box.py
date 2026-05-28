"""정면 박스 안 가장 가까운 사람 거리 — pure logic, rclpy 무관.

YOLO bbox + depth image → robot frame (forward, lateral) 변환 → 박스 필터.

graph_router 의 사람 감지 정지 트리거 (proximity_event.person_close) 용.
"""
from __future__ import annotations

from math import inf
from typing import Iterable

import numpy as np


def nearest_person_in_box(
    detections: Iterable[tuple[int, int, int, int]],
    depth: np.ndarray,
    fx: float,
    cx: float,
    box_forward_m: float,
    box_lateral_m: float,
) -> float:
    """정면 직사각형 박스 안 가장 가까운 사람 거리 (m). 없으면 +inf.

    Args:
        detections: bbox 리스트 [(x1, y1, x2, y2), ...] (image pixel).
        depth: depth image (H × W, uint16, mm).
        fx: 카메라 focal length (pixel).
        cx: 카메라 principal point x (pixel).
        box_forward_m: 박스 forward (m).
        box_lateral_m: 박스 좌우 절반 폭 (m).

    Returns:
        m 단위 가장 가까운 거리. 박스 안 사람 없으면 +inf.
    """
    nearest = inf
    if depth is None or depth.size == 0:
        return nearest
    H, W = depth.shape[:2]
    for x1, y1, x2, y2 in detections:
        bx = (x1 + x2) // 2
        by = (y1 + y2) // 2
        if not (0 <= bx < W and 0 <= by < H):
            continue
        d_mm = int(depth[by, bx])
        if d_mm <= 0:
            continue
        forward_m = d_mm / 1000.0
        lateral_m = (bx - cx) / fx * forward_m
        if forward_m > box_forward_m:
            continue
        if abs(lateral_m) > box_lateral_m:
            continue
        if forward_m < nearest:
            nearest = forward_m
    return nearest
