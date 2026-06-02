"""RotateToYaw 비례 감속(P-control) 단위 테스트.

순수 함수 ``compute_rotate_cmd`` 만 검증 — ROS / py_trees 의존 없음.
bang-bang(고정 속도) 이 실기에서 tolerance 밴드를 오버슈트해 왔다갔다(limit cycle)
하던 문제를, 목표 근처에서 속도를 줄이는 비례 감속으로 교체한 것을 보증한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

# gogoping_modes 패키지 path 등록 (test_gogoping_align_to_dock.py 와 동일)
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.behaviors.navigation.rotate_to_yaw import (  # noqa: E402
    compute_rotate_cmd,
)


# 기본 튜닝값 (rotate_to_yaw.py 와 일치)
ARGS = dict(tolerance=0.1, kp=1.5, min_speed=0.12, max_speed=0.5)


def test_within_tolerance_is_reached_with_zero_speed():
    cmd = compute_rotate_cmd(error=0.05, **ARGS)
    assert cmd.reached is True
    assert cmd.angular_z == 0.0


def test_far_positive_error_clamped_to_max_speed():
    # kp*0.5 = 0.75 > max → 0.5, 부호 +
    cmd = compute_rotate_cmd(error=0.5, **ARGS)
    assert cmd.reached is False
    assert cmd.angular_z == 0.5


def test_far_negative_error_clamped_to_max_speed():
    cmd = compute_rotate_cmd(error=-0.5, **ARGS)
    assert cmd.reached is False
    assert cmd.angular_z == -0.5


def test_proportional_in_ramp_zone():
    # error 0.2 → kp*0.2 = 0.3 (min<0.3<max) → 0.3
    cmd = compute_rotate_cmd(error=0.2, **ARGS)
    assert cmd.reached is False
    assert cmd.angular_z == pytest_approx(0.3)


def test_decelerates_as_error_shrinks():
    """핵심: 목표에 가까울수록 |속도| 가 작아져야 오버슈트가 안 난다."""
    far = abs(compute_rotate_cmd(error=0.4, **ARGS).angular_z)
    mid = abs(compute_rotate_cmd(error=0.25, **ARGS).angular_z)
    near = abs(compute_rotate_cmd(error=0.13, **ARGS).angular_z)
    assert far >= mid >= near
    assert near < 0.5  # 밴드 근처에선 풀스피드보다 확실히 느림


def test_min_speed_floor_prevents_stall():
    """밴드 밖인데 비례값이 너무 작으면 min_speed 로 끌어올린다 (정지마찰 극복)."""
    # tolerance 를 낮춰 error 0.06 이 밴드 밖이 되게: kp*0.06=0.09 < min 0.12 → 0.12
    cmd = compute_rotate_cmd(error=0.06, tolerance=0.05, kp=1.5, min_speed=0.12, max_speed=0.5)
    assert cmd.reached is False
    assert cmd.angular_z == pytest_approx(0.12)


def pytest_approx(value: float, tol: float = 1e-9):
    import pytest

    return pytest.approx(value, abs=tol)
