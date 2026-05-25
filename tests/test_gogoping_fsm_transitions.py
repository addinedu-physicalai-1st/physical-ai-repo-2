"""RobotFSM 평탄화 후 10 state + 13 trigger 매트릭스 검증.

각 trigger 가 정확히 어느 source state 에서 어느 dest state 로 가는지를 enumeration.
이 테스트가 fsm-triggers.md 의 명세를 코드로 박는 역할.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.fsm.robot_fsm import RobotFSM, STATES, TRANSITIONS  # noqa: E402


# ---------------------------------------------------------------- 기본 구조

def test_states_are_ten():
    assert set(STATES) == {
        "IDLE", "CHARGING", "GOTO", "FOLLOW", "LULLABY", "HIDEANDSEEK",
        "MANUAL", "RETURNING", "LOW_BATTERY_RETURN", "ERROR",
    }


def test_triggers_are_thirteen():
    trigger_names = {t["trigger"] for t in TRANSITIONS}
    assert trigger_names == {
        "battery_full", "goto_request", "follow_request", "lullaby_request",
        "hideseek_request", "manual_request", "return_request",
        "cancel", "task_done", "battery_low", "idle_timeout", "docked", "fault",
    }


def test_initial_state_is_charging():
    fsm = RobotFSM()
    assert fsm.current_state == "CHARGING"


# ---------------------------------------------------------------- 각 trigger 의 source/dest

# (trigger, from_state, expected_dest_state) — fsm-triggers.md spec 의 enumeration
_VALID_TRANSITIONS = [
    # battery_full
    ("battery_full", "CHARGING", "IDLE"),
    # goto_request
    ("goto_request", "IDLE", "GOTO"),
    ("goto_request", "FOLLOW", "GOTO"),
    ("goto_request", "LULLABY", "GOTO"),
    ("goto_request", "HIDEANDSEEK", "GOTO"),
    ("goto_request", "MANUAL", "GOTO"),
    ("goto_request", "RETURNING", "GOTO"),
    # follow_request
    ("follow_request", "IDLE", "FOLLOW"),
    ("follow_request", "GOTO", "FOLLOW"),
    ("follow_request", "LULLABY", "FOLLOW"),
    ("follow_request", "HIDEANDSEEK", "FOLLOW"),
    ("follow_request", "MANUAL", "FOLLOW"),
    ("follow_request", "RETURNING", "FOLLOW"),
    # lullaby_request
    ("lullaby_request", "IDLE", "LULLABY"),
    ("lullaby_request", "GOTO", "LULLABY"),
    ("lullaby_request", "FOLLOW", "LULLABY"),
    ("lullaby_request", "HIDEANDSEEK", "LULLABY"),
    ("lullaby_request", "MANUAL", "LULLABY"),
    ("lullaby_request", "RETURNING", "LULLABY"),
    # hideseek_request
    ("hideseek_request", "IDLE", "HIDEANDSEEK"),
    ("hideseek_request", "GOTO", "HIDEANDSEEK"),
    ("hideseek_request", "FOLLOW", "HIDEANDSEEK"),
    ("hideseek_request", "LULLABY", "HIDEANDSEEK"),
    ("hideseek_request", "MANUAL", "HIDEANDSEEK"),
    ("hideseek_request", "RETURNING", "HIDEANDSEEK"),
    # manual_request
    ("manual_request", "IDLE", "MANUAL"),
    ("manual_request", "GOTO", "MANUAL"),
    ("manual_request", "FOLLOW", "MANUAL"),
    ("manual_request", "LULLABY", "MANUAL"),
    ("manual_request", "HIDEANDSEEK", "MANUAL"),
    ("manual_request", "RETURNING", "MANUAL"),
    # return_request
    ("return_request", "IDLE", "RETURNING"),
    ("return_request", "GOTO", "RETURNING"),
    ("return_request", "FOLLOW", "RETURNING"),
    ("return_request", "LULLABY", "RETURNING"),
    ("return_request", "HIDEANDSEEK", "RETURNING"),
    ("return_request", "MANUAL", "RETURNING"),
    # cancel
    ("cancel", "GOTO", "IDLE"),
    ("cancel", "FOLLOW", "IDLE"),
    ("cancel", "LULLABY", "IDLE"),
    ("cancel", "HIDEANDSEEK", "IDLE"),
    ("cancel", "MANUAL", "IDLE"),
    ("cancel", "RETURNING", "IDLE"),
    # task_done
    ("task_done", "GOTO", "IDLE"),
    ("task_done", "FOLLOW", "IDLE"),
    ("task_done", "LULLABY", "IDLE"),
    ("task_done", "HIDEANDSEEK", "IDLE"),
    # battery_low (MANUAL 제외)
    ("battery_low", "IDLE", "LOW_BATTERY_RETURN"),
    ("battery_low", "GOTO", "LOW_BATTERY_RETURN"),
    ("battery_low", "FOLLOW", "LOW_BATTERY_RETURN"),
    ("battery_low", "LULLABY", "LOW_BATTERY_RETURN"),
    ("battery_low", "HIDEANDSEEK", "LOW_BATTERY_RETURN"),
    ("battery_low", "RETURNING", "LOW_BATTERY_RETURN"),
    # idle_timeout
    ("idle_timeout", "IDLE", "RETURNING"),
    # docked
    ("docked", "RETURNING", "CHARGING"),
    ("docked", "LOW_BATTERY_RETURN", "CHARGING"),
    # fault (ERROR 외 모두)
    ("fault", "CHARGING", "ERROR"),
    ("fault", "IDLE", "ERROR"),
    ("fault", "GOTO", "ERROR"),
    ("fault", "FOLLOW", "ERROR"),
    ("fault", "LULLABY", "ERROR"),
    ("fault", "HIDEANDSEEK", "ERROR"),
    ("fault", "MANUAL", "ERROR"),
    ("fault", "RETURNING", "ERROR"),
    ("fault", "LOW_BATTERY_RETURN", "ERROR"),
]


@pytest.mark.parametrize("trigger,src,dest", _VALID_TRANSITIONS)
def test_valid_transition(trigger, src, dest):
    fsm = RobotFSM(initial=src)
    ok = fsm.trigger(trigger)
    assert ok is True, f"{src} --[{trigger}]--> ??? failed (expected {dest})"
    assert fsm.current_state == dest


def test_error_is_terminal():
    """ERROR 에선 어떤 trigger 도 받지 않음 (terminal)."""
    fsm = RobotFSM(initial="IDLE")
    fsm.trigger("fault")
    assert fsm.current_state == "ERROR"
    # 모든 trigger 시도 — 전부 silently 무시 (False 반환)
    for trigger_name in {t["trigger"] for t in TRANSITIONS}:
        ok = fsm.trigger(trigger_name)
        assert ok is False, f"ERROR should reject {trigger_name}"
        assert fsm.current_state == "ERROR"


def test_low_battery_return_lockdown():
    """LOW_BATTERY_RETURN 에서는 docked / fault 만 받음."""
    fsm = RobotFSM(initial="LOW_BATTERY_RETURN")
    for trigger_name in {t["trigger"] for t in TRANSITIONS} - {"docked", "fault"}:
        ok = fsm.trigger(trigger_name)
        assert ok is False, f"LOW_BATTERY_RETURN should reject {trigger_name}"
        assert fsm.current_state == "LOW_BATTERY_RETURN"


def test_manual_ignores_battery_low_and_idle_timeout():
    """MANUAL 은 사용자가 직접 미는 중이라 자동 빼앗기 금지."""
    fsm = RobotFSM(initial="MANUAL")
    ok = fsm.trigger("battery_low")
    assert ok is False
    assert fsm.current_state == "MANUAL"
    ok = fsm.trigger("idle_timeout")
    assert ok is False
    assert fsm.current_state == "MANUAL"


def test_force_state_bypasses_transitions():
    """force_state 는 transition 규칙 우회 (디버그용)."""
    fsm = RobotFSM(initial="IDLE")
    ok = fsm.force_state("ERROR")
    assert ok is True
    assert fsm.current_state == "ERROR"


def test_on_state_change_callback_fires():
    """on_state_change 콜백이 transition 후 발화."""
    fsm = RobotFSM(initial="CHARGING")
    calls = []
    fsm.add_callback("on_state_change", lambda: calls.append(fsm.current_state))
    fsm.trigger("battery_full")
    assert calls == ["IDLE"]
    fsm.trigger("goto_request")
    assert calls == ["IDLE", "GOTO"]


def test_unknown_trigger_raises():
    fsm = RobotFSM(initial="IDLE")
    with pytest.raises(ValueError):
        fsm.trigger("nonexistent_trigger")
