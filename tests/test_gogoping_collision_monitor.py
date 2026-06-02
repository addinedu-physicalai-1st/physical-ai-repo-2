"""CollisionMonitor leaf 의 순수 로직 테스트.

collision_monitor(데이터 plane)가 stop 으로 cmd_vel 을 끊은 상태가 5분 이상
지속되면 FSM trigger 발화 — LOW_BATTERY_RETURNING 은 fault(→ERROR, 교사 호출),
그 외 주행 state(GOTO/RETURNING/HIDEANDSEEK)는 cancel(→IDLE).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.behaviors.common.collision_monitor import (  # noqa: E402
    evaluate_collision_timeout,
    timeout_trigger_for_state,
)

TIMEOUT = 300.0  # 5분


def test_not_stop_resets_timer():
    assert evaluate_collision_timeout("ok", stop_since=123.0, now=200.0,
                                      current_state="GOTO", timeout_s=TIMEOUT) == (None, None)


def test_first_stop_tick_starts_timer():
    assert evaluate_collision_timeout("stop", stop_since=None, now=10.0,
                                      current_state="GOTO", timeout_s=TIMEOUT) == (10.0, None)


def test_stop_below_timeout_keeps_running():
    # 10s 에 시작, 200s 경과(=190s < 300s)
    assert evaluate_collision_timeout("stop", stop_since=10.0, now=200.0,
                                      current_state="GOTO", timeout_s=TIMEOUT) == (10.0, None)


def test_stop_timeout_in_drive_state_fires_cancel():
    started, trig = evaluate_collision_timeout("stop", stop_since=10.0, now=10.0 + TIMEOUT,
                                               current_state="HIDEANDSEEK", timeout_s=TIMEOUT)
    assert started == 10.0
    assert trig == "cancel"


def test_stop_timeout_in_low_battery_fires_fault():
    _started, trig = evaluate_collision_timeout("stop", stop_since=10.0, now=10.0 + TIMEOUT,
                                                current_state="LOW_BATTERY_RETURNING", timeout_s=TIMEOUT)
    assert trig == "fault"


def test_trigger_mapping():
    assert timeout_trigger_for_state("LOW_BATTERY_RETURNING") == "fault"
    for s in ("GOTO", "RETURNING", "HIDEANDSEEK"):
        assert timeout_trigger_for_state(s) == "cancel"
