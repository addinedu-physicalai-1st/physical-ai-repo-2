"""Exponential moving average filter for TrackingState distance + angle.

perception 의 distance_m / angle_deg 가 frame-by-frame 으로 noise 가 있어
hysteresis decision (follow_decision.py) 이 oscillate 하는 것을 막는다.

이 모듈은 ROS 의존성이 없는 pure Python — unit test 가 직접 import.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FilteredState:
    distance_m: float
    angle_deg: float


class TrackingStateEMA:
    """단일 EMA. 첫 sample 은 그대로, 이후 alpha 가중 평균.

    distance_m 이 NaN 으로 들어오는 sample 은 이전 distance 값 유지 (각도는 갱신).
    """

    def __init__(self, alpha: float) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError(f"alpha must be in (0, 1], got {alpha}")
        self._alpha = alpha
        self._distance_m: float | None = None
        self._angle_deg: float | None = None

    def reset(self) -> None:
        self._distance_m = None
        self._angle_deg = None

    def update(self, distance_m: float, angle_deg: float) -> FilteredState:
        a = self._alpha
        # angle 은 항상 갱신
        if self._angle_deg is None:
            self._angle_deg = angle_deg
        else:
            self._angle_deg = (1.0 - a) * self._angle_deg + a * angle_deg

        # distance 는 NaN 일 때 hold
        if math.isnan(distance_m):
            d_out = self._distance_m if self._distance_m is not None else float("nan")
        elif self._distance_m is None:
            self._distance_m = distance_m
            d_out = distance_m
        else:
            self._distance_m = (1.0 - a) * self._distance_m + a * distance_m
            d_out = self._distance_m

        return FilteredState(distance_m=d_out, angle_deg=self._angle_deg)
