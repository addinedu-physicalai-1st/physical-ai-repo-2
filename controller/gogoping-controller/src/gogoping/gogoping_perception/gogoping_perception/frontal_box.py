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


def _central_band_roi(
    depth: np.ndarray,
    row_top_frac: float,
    row_bot_frac: float,
    col_half_frac: float,
) -> "tuple[np.ndarray, int, int, int, int] | None":
    """정면 중앙 밴드 ROI 슬라이스 + 경계(r0, r1, c0, c1) 반환. 빈/퇴화 ROI 면 None.

    바닥(하단)·천장(상단) 제외 위해 세로는 중앙 밴드(row_top~row_bot), 좌우는 중앙
    col_half 만. nearest_obstacle_forward / nearest_in_box_split 공용 (ROI 정의 단일화).
    """
    if depth is None or depth.size == 0:
        return None
    H, W = depth.shape[:2]
    r0 = max(0, int(H * row_top_frac))
    r1 = min(H, int(H * row_bot_frac))
    cc = W // 2
    cw = int(W * col_half_frac)
    c0 = max(0, cc - cw)
    c1 = min(W, cc + cw)
    if r1 <= r0 or c1 <= c0:
        return None
    return depth[r0:r1, c0:c1], r0, r1, c0, c1


def nearest_obstacle_forward(
    depth: np.ndarray,
    *,
    depth_min_mm: int,
    depth_max_mm: int,
    row_top_frac: float,
    row_bot_frac: float,
    col_half_frac: float,
    percentile: float,
) -> float:
    """정면 중앙 밴드의 최근접(저백분위) 거리 (m). 유효값 없으면 +inf.

    사람 detection 무관 — depth 만으로 계산. 바닥은 영상 하단에 잡히므로
    중앙 수평 밴드(row_top_frac~row_bot_frac)만 본다. 좌우는 중앙
    col_half_frac 만큼만(전방 한정). speckle 노이즈 회피로 최소값 대신
    저백분위(percentile)를 쓴다.

    Args:
        depth: depth image (H × W, uint16, mm).
        depth_min_mm / depth_max_mm: 유효 depth 범위 (mm).
        row_top_frac / row_bot_frac: ROI 세로 밴드 (H 비율, 0~1).
        col_half_frac: ROI 좌우 절반폭 (W 비율, 0~0.5).
        percentile: 0~100. 작을수록 더 "가까운" 값.

    Returns:
        m 단위 최근접 거리. ROI 안 유효 depth 없으면 +inf.
    """
    roi_info = _central_band_roi(depth, row_top_frac, row_bot_frac, col_half_frac)
    if roi_info is None:
        return inf
    roi = roi_info[0]
    valid = roi[(roi >= depth_min_mm) & (roi <= depth_max_mm)]
    if valid.size == 0:
        return inf
    return float(np.percentile(valid, percentile)) / 1000.0


def nearest_in_box_split(
    depth: np.ndarray,
    detections: Iterable[tuple[int, int, int, int]],
    *,
    depth_min_mm: int,
    depth_max_mm: int,
    row_top_frac: float,
    row_bot_frac: float,
    col_half_frac: float,
    percentile: float,
) -> tuple[float, float]:
    """정면 중앙 ROI 를 사람 bbox / 비-사람 픽셀로 나눠 각각 최근접(저백분위) 거리(m).

    ROI 정의는 nearest_obstacle_forward 와 동일. ROI 안 유효 depth 중
    어떤 사람 bbox 와 겹치는 픽셀은 person, 나머지는 obstacle 로 분류한다.
    rqt debug_image 에서 "가까운 쪽"(사람/사물)을 표시하기 위한 용도.

    Args:
        depth: depth image (H × W, uint16, mm).
        detections: 사람 bbox 리스트 [(x1, y1, x2, y2), ...] (image pixel).
        depth_min_mm / depth_max_mm: 유효 depth 범위 (mm).
        row_top_frac / row_bot_frac: ROI 세로 밴드 (H 비율, 0~1).
        col_half_frac: ROI 좌우 절반폭 (W 비율, 0~0.5).
        percentile: 0~100. 작을수록 더 "가까운" 값.

    Returns:
        (person_m, obstacle_m). 각 분류에 유효 픽셀 없으면 해당 값 +inf.
    """
    roi_info = _central_band_roi(depth, row_top_frac, row_bot_frac, col_half_frac)
    if roi_info is None:
        return inf, inf
    roi, r0, r1, c0, c1 = roi_info
    valid = (roi >= depth_min_mm) & (roi <= depth_max_mm)
    person = np.zeros(roi.shape, dtype=bool)
    for x1, y1, x2, y2 in detections:
        bx0 = max(int(x1), c0) - c0
        bx1 = min(int(x2), c1) - c0
        by0 = max(int(y1), r0) - r0
        by1 = min(int(y2), r1) - r0
        if bx1 > bx0 and by1 > by0:
            person[by0:by1, bx0:bx1] = True
    person_vals = roi[valid & person]
    obstacle_vals = roi[valid & ~person]
    person_m = (
        float(np.percentile(person_vals, percentile)) / 1000.0
        if person_vals.size else inf
    )
    obstacle_m = (
        float(np.percentile(obstacle_vals, percentile)) / 1000.0
        if obstacle_vals.size else inf
    )
    return person_m, obstacle_m
