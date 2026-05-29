"""recovery_body_planner pure-function tests."""
from __future__ import annotations

import math

import pytest

from gogoping_follow.recovery_body_planner import (
    BodyPhase,
    BodyState,
    compute_pan_step,
    consume_body_turn,
    initial_state,
    on_body_turn_complete,
    on_narrow_sweep_reach_target,
    on_sweep_complete,
)


# Common config (matches gogoping_follow.config)
LEFT = 150.0
RIGHT = 30.0
FRONT = 90.0
NARROW_HALF = 45.0
BODY_TURN = 25.0
MAX_TOTAL = 360.0


# ---------- initial_state ----------

def test_initial_state_from_front_goes_left():
    """PAN 정면 (90°) 진입 → 좌측 끝(150°) 으로 sweep 시작."""
    s = initial_state(current_pan_deg=90.0, pan_left_deg=LEFT, pan_right_deg=RIGHT)
    assert s.phase == BodyPhase.FULL_SWEEP
    assert s.pan_target_deg == LEFT
    assert s.total_body_turn_deg == 0.0


def test_initial_state_from_right_goes_left():
    """PAN 우측(30°) 진입 → 좌측(150°) 으로 sweep (긴 쪽)."""
    s = initial_state(current_pan_deg=RIGHT, pan_left_deg=LEFT, pan_right_deg=RIGHT)
    assert s.pan_target_deg == LEFT


def test_initial_state_from_left_goes_right():
    """PAN 좌측(150°) 진입 → 우측(30°) 으로 sweep (긴 쪽)."""
    s = initial_state(current_pan_deg=LEFT, pan_left_deg=LEFT, pan_right_deg=RIGHT)
    assert s.pan_target_deg == RIGHT


# ---------- on_sweep_complete ----------

def test_sweep_complete_pan_at_right_turns_cw():
    """FULL_SWEEP 종료 시 PAN 이 우측(30°) → 본체 우회전 (yaw_dir = -1)."""
    s = BodyState(
        phase=BodyPhase.FULL_SWEEP, pan_target_deg=RIGHT, yaw_dir=0,
        body_turn_remaining_rad=0.0, total_body_turn_deg=0.0,
    )
    s2 = on_sweep_complete(s, LEFT, RIGHT, BODY_TURN, MAX_TOTAL)
    assert s2.phase == BodyPhase.BODY_TURN
    assert s2.yaw_dir == -1
    assert s2.body_turn_remaining_rad == pytest.approx(math.radians(BODY_TURN))
    assert s2.total_body_turn_deg == BODY_TURN


def test_sweep_complete_pan_at_left_turns_ccw():
    """FULL_SWEEP 종료 시 PAN 이 좌측(150°) → 본체 좌회전 (yaw_dir = +1)."""
    s = BodyState(
        phase=BodyPhase.FULL_SWEEP, pan_target_deg=LEFT, yaw_dir=0,
        body_turn_remaining_rad=0.0, total_body_turn_deg=0.0,
    )
    s2 = on_sweep_complete(s, LEFT, RIGHT, BODY_TURN, MAX_TOTAL)
    assert s2.yaw_dir == +1


def test_sweep_complete_exceeds_max_total_goes_exhausted():
    """누적 + 다음 회전 > 360 → EXHAUSTED."""
    s = BodyState(
        phase=BodyPhase.NARROW_SWEEP, pan_target_deg=RIGHT, yaw_dir=0,
        body_turn_remaining_rad=0.0, total_body_turn_deg=350.0,  # +25=375 > 360
    )
    s2 = on_sweep_complete(s, LEFT, RIGHT, BODY_TURN, MAX_TOTAL)
    assert s2.phase == BodyPhase.EXHAUSTED
    assert s2.total_body_turn_deg == 350.0  # 회전 안 함


# ---------- on_body_turn_complete ----------

def test_body_turn_complete_transitions_to_narrow():
    """BODY_TURN 종료 → NARROW_SWEEP, 현재 PAN 반대 끝으로."""
    s = BodyState(
        phase=BodyPhase.BODY_TURN, pan_target_deg=RIGHT, yaw_dir=-1,
        body_turn_remaining_rad=0.0, total_body_turn_deg=BODY_TURN,
    )
    s2 = on_body_turn_complete(s, current_pan_deg=30.0,
                                narrow_pan_front_deg=FRONT,
                                narrow_pan_half_deg=NARROW_HALF)
    assert s2.phase == BodyPhase.NARROW_SWEEP
    assert s2.pan_target_deg == FRONT + NARROW_HALF  # = 135 (좌측 끝)
    assert s2.total_body_turn_deg == BODY_TURN


def test_body_turn_complete_from_left_pan_goes_to_right_narrow():
    """BODY_TURN 종료 시 PAN 이 좌측이면 narrow sweep 은 우측(45°) 으로."""
    s = BodyState(
        phase=BodyPhase.BODY_TURN, pan_target_deg=LEFT, yaw_dir=+1,
        body_turn_remaining_rad=0.0, total_body_turn_deg=BODY_TURN,
    )
    s2 = on_body_turn_complete(s, current_pan_deg=150.0,
                                narrow_pan_front_deg=FRONT,
                                narrow_pan_half_deg=NARROW_HALF)
    assert s2.pan_target_deg == FRONT - NARROW_HALF  # = 45 (우측 끝)


# ---------- on_narrow_sweep_reach_target ----------

def test_narrow_sweep_reach_left_switches_to_right():
    """NARROW 좌측(135) 도달 → 우측(45) 으로 전환."""
    s = BodyState(
        phase=BodyPhase.NARROW_SWEEP, pan_target_deg=135.0, yaw_dir=0,
        body_turn_remaining_rad=0.0, total_body_turn_deg=BODY_TURN,
    )
    s2 = on_narrow_sweep_reach_target(s, FRONT, NARROW_HALF)
    assert s2.pan_target_deg == 45.0


# ---------- compute_pan_step ----------

def test_pan_step_normal():
    """정상 ramp — 도달 안 함."""
    next_pan, reached = compute_pan_step(90.0, 150.0, rate_deg_s=10.0, dt=0.5)
    assert next_pan == 95.0
    assert reached is False


def test_pan_step_reach():
    """남은 거리 < step → 도달, reached=True."""
    next_pan, reached = compute_pan_step(149.0, 150.0, rate_deg_s=10.0, dt=0.5)
    assert next_pan == 150.0
    assert reached is True


def test_pan_step_reverse_direction():
    """current > target → 음수 step."""
    next_pan, _ = compute_pan_step(150.0, 30.0, rate_deg_s=10.0, dt=0.5)
    assert next_pan == 145.0


# ---------- consume_body_turn ----------

def test_consume_body_turn_in_progress():
    """본체 회전 중 — completed=False."""
    s = BodyState(
        phase=BodyPhase.BODY_TURN, pan_target_deg=30.0, yaw_dir=-1,
        body_turn_remaining_rad=math.radians(25.0), total_body_turn_deg=25.0,
    )
    s2, completed = consume_body_turn(s, rate_rad_s=0.6, dt=0.5)
    assert completed is False
    # 0.6 × 0.5 = 0.3 rad, 25° ≈ 0.436 rad → 남은 0.136 rad
    assert s2.body_turn_remaining_rad == pytest.approx(math.radians(25.0) - 0.3)


def test_consume_body_turn_completes():
    """남은 회전 < step → completed=True."""
    s = BodyState(
        phase=BodyPhase.BODY_TURN, pan_target_deg=30.0, yaw_dir=-1,
        body_turn_remaining_rad=0.05, total_body_turn_deg=25.0,
    )
    _, completed = consume_body_turn(s, rate_rad_s=0.6, dt=0.5)
    assert completed is True


# ---------- end-to-end (state machine 흐름) ----------

def test_full_loop_until_exhausted_at_360():
    """FULL_SWEEP → BODY_TURN ×14 → narrow_sweep 14번 → 375° 시점 EXHAUSTED."""
    # FULL_SWEEP 끝 (PAN 좌측 150) 가정
    s = BodyState(
        phase=BodyPhase.FULL_SWEEP, pan_target_deg=LEFT, yaw_dir=0,
        body_turn_remaining_rad=0.0, total_body_turn_deg=0.0,
    )
    # 첫 sweep_complete → BODY_TURN, total=25
    s = on_sweep_complete(s, LEFT, RIGHT, BODY_TURN, MAX_TOTAL)
    assert s.phase == BodyPhase.BODY_TURN
    assert s.total_body_turn_deg == 25.0

    # 이후 NARROW_SWEEP → BODY_TURN 반복 — 13번 더 (총 14 BODY_TURN → 350°)
    for i in range(13):
        s = on_body_turn_complete(s, current_pan_deg=LEFT,
                                    narrow_pan_front_deg=FRONT,
                                    narrow_pan_half_deg=NARROW_HALF)
        assert s.phase == BodyPhase.NARROW_SWEEP
        s = on_sweep_complete(s, LEFT, RIGHT, BODY_TURN, MAX_TOTAL)
        assert s.phase == BodyPhase.BODY_TURN

    assert s.total_body_turn_deg == 350.0
    # 다음 narrow → sweep_complete → 350+25=375 > 360 → EXHAUSTED
    s = on_body_turn_complete(s, current_pan_deg=LEFT,
                                narrow_pan_front_deg=FRONT,
                                narrow_pan_half_deg=NARROW_HALF)
    s = on_sweep_complete(s, LEFT, RIGHT, BODY_TURN, MAX_TOTAL)
    assert s.phase == BodyPhase.EXHAUSTED
