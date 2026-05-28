"""EMA filter unit tests — distance_m + angle_deg smoothing.

Pure-Python logic, no ROS imports.
"""
import math

import pytest

from gogoping_follow.state_filter import TrackingStateEMA


def test_initial_sample_returns_itself() -> None:
    f = TrackingStateEMA(alpha=0.3)
    out = f.update(distance_m=1.0, angle_deg=10.0)
    assert out.distance_m == pytest.approx(1.0)
    assert out.angle_deg == pytest.approx(10.0)


def test_steady_state_converges_to_input() -> None:
    f = TrackingStateEMA(alpha=0.3)
    for _ in range(50):
        out = f.update(distance_m=1.5, angle_deg=-5.0)
    assert out.distance_m == pytest.approx(1.5, abs=1e-3)
    assert out.angle_deg == pytest.approx(-5.0, abs=1e-3)


def test_single_spike_dampened() -> None:
    f = TrackingStateEMA(alpha=0.3)
    # 안정 상태
    for _ in range(20):
        f.update(distance_m=1.0, angle_deg=0.0)
    # spike 1 개 — 30% 만 반영되어야 함
    out = f.update(distance_m=5.0, angle_deg=45.0)
    assert 1.0 < out.distance_m < 2.5
    assert 0.0 < out.angle_deg < 15.0


def test_nan_distance_propagates_without_corrupting_state() -> None:
    """perception 이 distance_m=NaN 으로 publish 하는 경우 (depth invalid)."""
    f = TrackingStateEMA(alpha=0.3)
    f.update(distance_m=1.0, angle_deg=0.0)
    out = f.update(distance_m=float("nan"), angle_deg=5.0)
    # 거리 NaN 입력은 이전값 유지, angle 만 갱신
    assert out.distance_m == pytest.approx(1.0)
    assert out.angle_deg == pytest.approx(1.5, abs=1e-3)  # 0*0.7 + 5*0.3


def test_reset_clears_state() -> None:
    f = TrackingStateEMA(alpha=0.3)
    f.update(distance_m=2.0, angle_deg=20.0)
    f.reset()
    out = f.update(distance_m=0.5, angle_deg=-10.0)
    assert out.distance_m == pytest.approx(0.5)
    assert out.angle_deg == pytest.approx(-10.0)
