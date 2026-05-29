"""Unit tests for voice_search_planner."""
import math

import pytest

from gogoping_follow.voice_search_planner import (
    SweepPhase,
    compute_voice_resume_yaw,
    compute_voice_sweep_step,
)


# ---------- compute_voice_sweep_step ----------
def test_to_home_start_moves_toward_90():
    next_pan, next_phase = compute_voice_sweep_step(
        current=120.0, phase=SweepPhase.TO_HOME_START,
        rate=10.0, dt=0.1,
        pan_home=90.0, pan_left=5.0, pan_right=175.0,
    )
    # 10°/s × 0.1 = 1° 진행, 120 → 119
    assert next_pan == pytest.approx(119.0)
    assert next_phase == SweepPhase.TO_HOME_START


def test_to_home_start_reaches_home_transitions_to_left():
    next_pan, next_phase = compute_voice_sweep_step(
        current=90.5, phase=SweepPhase.TO_HOME_START,
        rate=10.0, dt=0.1,
        pan_home=90.0, pan_left=5.0, pan_right=175.0,
    )
    assert next_pan == pytest.approx(90.0)
    assert next_phase == SweepPhase.TO_LEFT


def test_to_left_moves_toward_5():
    next_pan, next_phase = compute_voice_sweep_step(
        current=90.0, phase=SweepPhase.TO_LEFT,
        rate=10.0, dt=0.1,
        pan_home=90.0, pan_left=5.0, pan_right=175.0,
    )
    assert next_pan == pytest.approx(89.0)
    assert next_phase == SweepPhase.TO_LEFT


def test_to_left_reaches_5_transitions_to_right():
    next_pan, next_phase = compute_voice_sweep_step(
        current=5.5, phase=SweepPhase.TO_LEFT,
        rate=10.0, dt=0.1,
        pan_home=90.0, pan_left=5.0, pan_right=175.0,
    )
    assert next_pan == pytest.approx(5.0)
    assert next_phase == SweepPhase.TO_RIGHT


def test_to_right_reaches_175_transitions_to_home_end():
    next_pan, next_phase = compute_voice_sweep_step(
        current=174.5, phase=SweepPhase.TO_RIGHT,
        rate=10.0, dt=0.1,
        pan_home=90.0, pan_left=5.0, pan_right=175.0,
    )
    assert next_pan == pytest.approx(175.0)
    assert next_phase == SweepPhase.TO_HOME_END


def test_to_home_end_reaches_90_transitions_to_done():
    next_pan, next_phase = compute_voice_sweep_step(
        current=90.5, phase=SweepPhase.TO_HOME_END,
        rate=10.0, dt=0.1,
        pan_home=90.0, pan_left=5.0, pan_right=175.0,
    )
    assert next_pan == pytest.approx(90.0)
    assert next_phase == SweepPhase.DONE


def test_done_phase_holds():
    next_pan, next_phase = compute_voice_sweep_step(
        current=90.0, phase=SweepPhase.DONE,
        rate=10.0, dt=0.1,
        pan_home=90.0, pan_left=5.0, pan_right=175.0,
    )
    assert next_pan == 90.0
    assert next_phase == SweepPhase.DONE


# ---------- compute_voice_resume_yaw ----------
def test_resume_yaw_home_returns_zero():
    assert compute_voice_resume_yaw(90.0) == pytest.approx(0.0)


def test_resume_yaw_right_returns_negative():
    # PAN 30° = 우측 60° → robot 우회전 = -60° = -π/3
    assert compute_voice_resume_yaw(30.0) == pytest.approx(-math.pi / 3, abs=1e-6)


def test_resume_yaw_left_returns_positive():
    # PAN 150° = 좌측 60° → robot 좌회전 = +60° = +π/3
    assert compute_voice_resume_yaw(150.0) == pytest.approx(math.pi / 3, abs=1e-6)


def test_resume_yaw_extreme_left():
    assert compute_voice_resume_yaw(5.0) == pytest.approx(math.radians(-85), abs=1e-6)


def test_resume_yaw_extreme_right():
    assert compute_voice_resume_yaw(175.0) == pytest.approx(math.radians(85), abs=1e-6)
