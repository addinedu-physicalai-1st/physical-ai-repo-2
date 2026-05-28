"""Unit tests for recovery — graph candidate / hint mapping / PAN step."""
import math

import pytest

from gogoping_follow.recovery import (
    HintAction,
    RecoveryCandidate,
    compute_candidates,
    compute_pan_step,
    hint_to_action,
)


# ---------- compute_candidates ----------
def test_compute_candidates_empty_when_no_adjacent():
    # robot at (0,0,0), adjacency empty
    cands = compute_candidates(
        robot_xy=(0.0, 0.0),
        robot_yaw=0.0,
        adjacent_vertices=[],
        max_dist=5.0,
        pan_min=5.0,
        pan_max=175.0,
    )
    assert cands == []


def test_compute_candidates_front_vertex():
    # vertex 정면 2m → pan=90°, dist=2
    cands = compute_candidates(
        robot_xy=(0.0, 0.0),
        robot_yaw=0.0,
        adjacent_vertices=[("V1", 2.0, 0.0)],
        max_dist=5.0,
        pan_min=5.0,
        pan_max=175.0,
    )
    assert len(cands) == 1
    assert cands[0].vertex_name == "V1"
    assert cands[0].pan_deg == pytest.approx(90.0, abs=1e-6)
    assert cands[0].distance_m == pytest.approx(2.0)


def test_compute_candidates_left_vertex():
    # vertex 좌측 60° (앞쪽 살짝 좌측) → robot frame yaw +60° = PAN 150°
    cands = compute_candidates(
        robot_xy=(0.0, 0.0),
        robot_yaw=0.0,
        adjacent_vertices=[("Vleft", math.cos(math.radians(60)) * 2.0,
                            math.sin(math.radians(60)) * 2.0)],
        max_dist=5.0,
        pan_min=5.0,
        pan_max=175.0,
    )
    assert len(cands) == 1
    assert cands[0].pan_deg == pytest.approx(150.0, abs=0.5)


def test_compute_candidates_filters_pan_range():
    # 정확히 90° 좌측 (+y) → PAN 180° → 175° max 초과 → 제외
    cands = compute_candidates(
        robot_xy=(0.0, 0.0),
        robot_yaw=0.0,
        adjacent_vertices=[("Vside", 0.0, 2.0)],
        max_dist=5.0,
        pan_min=5.0,
        pan_max=175.0,
    )
    assert cands == []


def test_compute_candidates_filters_max_dist():
    # 정면 10m → 5m max 초과 → 제외
    cands = compute_candidates(
        robot_xy=(0.0, 0.0),
        robot_yaw=0.0,
        adjacent_vertices=[("Vfar", 10.0, 0.0)],
        max_dist=5.0,
        pan_min=5.0,
        pan_max=175.0,
    )
    assert cands == []


def test_compute_candidates_robot_yaw_offset():
    # robot yaw=90° (정면이 +y). vertex 가 (2, 0) — robot frame 으로 우측 → PAN < 90
    # base_link yaw = atan2(0, 2) - π/2 = -π/2 → PAN = 90 + (-90) = 0
    # pan_min=5 미만 → 제외
    cands = compute_candidates(
        robot_xy=(0.0, 0.0),
        robot_yaw=math.radians(90),
        adjacent_vertices=[("Vfwd", 2.0, 0.0)],
        max_dist=5.0,
        pan_min=5.0,
        pan_max=175.0,
    )
    assert cands == []


def test_compute_candidates_sorted_by_pan_proximity_to_center():
    cands = compute_candidates(
        robot_xy=(0.0, 0.0),
        robot_yaw=0.0,
        adjacent_vertices=[
            ("V_far_left", math.cos(math.radians(80)) * 2.0,
                            math.sin(math.radians(80)) * 2.0),    # ~PAN 170 (멀음)
            ("V_near_center", math.cos(math.radians(10)) * 2.0,
                              math.sin(math.radians(10)) * 2.0),   # ~PAN 100 (가까움)
        ],
        max_dist=5.0,
        pan_min=5.0,
        pan_max=175.0,
    )
    assert len(cands) == 2
    # PAN 100 이 PAN 170 보다 center(90) 에 가까움 → 먼저
    assert cands[0].vertex_name == "V_near_center"
    assert cands[1].vertex_name == "V_far_left"


# ---------- hint_to_action ----------
HINT_P = dict(
    pan_left=150.0,
    pan_right=30.0,
    pan_front=90.0,
    back_turn_rate_rad_s=0.6,
    dwell=2.5,
)


def test_hint_right():
    a = hint_to_action("right", **HINT_P)
    assert a is not None
    assert a.pan_target_deg == 30.0
    assert a.base_rotate_rad == 0.0
    assert a.dwell_s == 2.5


def test_hint_left():
    a = hint_to_action("left", **HINT_P)
    assert a is not None
    assert a.pan_target_deg == 150.0
    assert a.base_rotate_rad == 0.0


def test_hint_front():
    a = hint_to_action("front", **HINT_P)
    assert a is not None
    assert a.pan_target_deg == 90.0
    assert a.base_rotate_rad == 0.0


def test_hint_back():
    a = hint_to_action("back", **HINT_P)
    assert a is not None
    assert a.pan_target_deg == 90.0
    assert a.base_rotate_rad == pytest.approx(math.pi)  # 180°


def test_hint_unknown_returns_none():
    assert hint_to_action("up", **HINT_P) is None
    assert hint_to_action("", **HINT_P) is None
    assert hint_to_action("RIGHT", **HINT_P) is None  # 대소문자 구분


# ---------- compute_pan_step ----------
def test_pan_step_far_returns_rate_dt():
    # current=90, target=30 (60° 차이), rate=10°/s, dt=0.5s → step = 5°
    step = compute_pan_step(current=90.0, target=30.0, rate=10.0, dt=0.5)
    assert step == pytest.approx(-5.0)  # 음수 = current 가 감소


def test_pan_step_near_clamps_to_remaining():
    # current=32, target=30, rate=10, dt=1.0 → 남은 2° 만
    step = compute_pan_step(current=32.0, target=30.0, rate=10.0, dt=1.0)
    assert step == pytest.approx(-2.0)


def test_pan_step_reached_returns_zero():
    step = compute_pan_step(current=30.0, target=30.0, rate=10.0, dt=0.5)
    assert step == 0.0


def test_pan_step_positive_direction():
    step = compute_pan_step(current=90.0, target=150.0, rate=10.0, dt=0.3)
    assert step == pytest.approx(3.0)
