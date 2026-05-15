"""LiDAR 폴라 데이터 → 화면 좌표 / 방향별 빈 평균 — 순수 함수.

PyQt 의존 없이 테스트 가능하도록 분리.
"""

from __future__ import annotations

import math
from typing import Optional


def polar_to_screen(
    *,
    theta: float,
    r: float,
    max_r: float,
    radius: float,
    cx: float,
    cy: float,
) -> tuple[float, float]:
    """ROS REP 103 (x 전방, y 좌, 반시계 양수) → Qt screen (x 오른쪽, y 아래).

    결과: 전방=화면 위, 좌=화면 왼쪽, 우=화면 오른쪽, 후=화면 아래.

    참조: traffic_light_4way_gui_intersection_fixed.py:142-145 4방향 좌표 컨벤션.
    """
    r_clip = min(r, max_r) if r > 0 else 0.0
    px = cx - (r_clip / max_r) * radius * math.sin(theta)
    py = cy - (r_clip / max_r) * radius * math.cos(theta)
    return px, py


def _wrap_pi(angle: float) -> float:
    """angle 을 [-π, π) 범위로."""
    return (angle + math.pi) % (2 * math.pi) - math.pi


def bin_directions(
    ranges: list[float],
    *,
    angle_min: float,
    angle_inc: float,
    half_width_deg: float = 15.0,
) -> dict[str, Optional[float]]:
    """4 방향 (앞/뒤/좌/우) ±half_width 영역의 유효 점 평균 거리.

    유효 = finite & > 0. 영역에 유효 점이 0 개면 None.

    방향 기준 (ROS REP 103):
      front =  0,  back =  π,  left =  π/2,  right = -π/2
    """
    if not ranges or angle_inc == 0.0:
        return {"front": None, "back": None, "left": None, "right": None}

    half = math.radians(half_width_deg)
    centers = {"front": 0.0, "back": math.pi, "left": math.pi / 2, "right": -math.pi / 2}
    buckets: dict[str, list[float]] = {k: [] for k in centers}

    for i, r in enumerate(ranges):
        if not math.isfinite(r) or r <= 0.0:
            continue
        theta = _wrap_pi(angle_min + i * angle_inc)
        for name, c in centers.items():
            delta = _wrap_pi(theta - c)
            if abs(delta) <= half:
                buckets[name].append(r)

    return {
        k: (sum(v) / len(v)) if v else None
        for k, v in buckets.items()
    }
