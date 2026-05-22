"""LaserScan + 특정 방위(rad) → 거리(m) 추정.

bbox 의 카메라 frame 방위와 LiDAR 의 방위가 같다고 가정 (카메라/LiDAR co-located,
robot heading 일치). 다른 mount 라면 fixed offset 더해 호출.
"""
from __future__ import annotations

import math
from typing import Sequence


def distance_at_bearing(
    ranges: Sequence[float],
    angle_min: float,
    angle_increment: float,
    bearing_rad: float,
    window_rad: float,
    *,
    max_m: float = 8.0,
) -> float | None:
    """`bearing_rad` 근처 ±`window_rad / 2` 의 유효 빔 평균 거리. 없으면 None.

    ranges: LaserScan.ranges (list of float, inf/nan 가능)
    angle_min, angle_increment: LaserScan 헤더 값 (rad)
    bearing_rad: 0 = 정면, +π/2 = 좌, -π/2 = 우 (REP-103)
    window_rad: 평균 낼 window 폭
    max_m: 이 이상은 신뢰 안 함
    """
    n = len(ranges)
    if n == 0:
        return None

    lo = bearing_rad - window_rad / 2.0
    hi = bearing_rad + window_rad / 2.0

    valid: list[float] = []
    for i, r in enumerate(ranges):
        if not math.isfinite(r) or r <= 0.05 or r > max_m:
            continue
        a = angle_min + i * angle_increment
        if lo <= a <= hi:
            valid.append(r)

    if not valid:
        return None
    return sum(valid) / len(valid)
