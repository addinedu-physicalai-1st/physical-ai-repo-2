"""goal_reconciler.reconcile() 평탄화 모델 테스트.

target_state 직접 매핑 — mode/task 두 축이 없음.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.utils.goal_reconciler import reconcile  # noqa: E402


def _bb_and_fsm(current="IDLE"):
    bb = MagicMock()
    fsm = MagicMock()
    fsm.current_state = current
    fsm.trigger.return_value = True
    return bb, fsm


# ---------------------------------------------------------------- validation

def test_unknown_target_state_rejected():
    bb, fsm = _bb_and_fsm()
    result = reconcile({"target_state": "BANANA"}, fsm=fsm, blackboard=bb)
    assert result.accepted is False
    assert result.reason == "invalid_target_state"


def test_internal_only_states_rejected():
    """CHARGING / LOW_BATTERY_RETURNING / ERROR 는 외부에서 직접 요청 불가."""
    for s in ("CHARGING", "LOW_BATTERY_RETURNING", "ERROR"):
        bb, fsm = _bb_and_fsm()
        result = reconcile({"target_state": s}, fsm=fsm, blackboard=bb)
        assert result.accepted is False
        assert result.reason == "internal_only_state"


# ---------------------------------------------------------------- GOTO

def test_goto_with_destination_accepted():
    bb, fsm = _bb_and_fsm()
    result = reconcile(
        {"target_state": "GOTO", "destination_key": "교실A"},
        fsm=fsm, blackboard=bb,
    )
    assert result.accepted is True
    assert result.trigger_fired == "goto_request"
    setters = {c.args[0]: c.args[1] for c in bb.set.call_args_list}
    assert setters["destination_key"] == "교실A"


def test_goto_missing_destination_rejected():
    bb, fsm = _bb_and_fsm()
    result = reconcile({"target_state": "GOTO", "destination_key": ""}, fsm=fsm, blackboard=bb)
    assert result.accepted is False
    assert result.reason == "missing_destination"
    fsm.trigger.assert_not_called()


# ---------------------------------------------------------------- FOLLOW

def test_follow_with_target_accepted():
    bb, fsm = _bb_and_fsm()
    result = reconcile(
        {"target_state": "FOLLOW", "target_id": "teacher_A"},
        fsm=fsm, blackboard=bb,
    )
    assert result.accepted is True
    assert result.trigger_fired == "follow_request"
    setters = {c.args[0]: c.args[1] for c in bb.set.call_args_list}
    assert setters["target_person_id"] == "teacher_A"


def test_follow_missing_target_rejected():
    bb, fsm = _bb_and_fsm()
    result = reconcile({"target_state": "FOLLOW", "target_id": ""}, fsm=fsm, blackboard=bb)
    assert result.accepted is False
    assert result.reason == "missing_target_id"


# ---------------------------------------------------------------- LULLABY

def test_lullaby_accepted_no_extra_fields():
    bb, fsm = _bb_and_fsm()
    result = reconcile({"target_state": "LULLABY"}, fsm=fsm, blackboard=bb)
    assert result.accepted is True
    assert result.trigger_fired == "lullaby_request"


# ---------------------------------------------------------------- HIDEANDSEEK

def test_hideseek_with_target_and_waypoints_accepted():
    bb, fsm = _bb_and_fsm()
    result = reconcile(
        {
            "target_state": "HIDEANDSEEK",
            "target_id": "child_42",
            "search_waypoints": ["A", "B", "C"],
            "play_area_key": "play_area",
        },
        fsm=fsm, blackboard=bb,
    )
    assert result.accepted is True
    assert result.trigger_fired == "hideseek_request"
    setters = {c.args[0]: c.args[1] for c in bb.set.call_args_list}
    assert setters["target_person_id"] == "child_42"
    assert setters["search_waypoints"] == ["A", "B", "C"]


def test_hideseek_missing_search_waypoints_rejected():
    bb, fsm = _bb_and_fsm()
    result = reconcile(
        {
            "target_state": "HIDEANDSEEK",
            "target_id": "x",
            "search_waypoints": [],
            "play_area_key": "play_area",
        },
        fsm=fsm, blackboard=bb,
    )
    assert result.accepted is False
    assert result.reason == "missing_search_waypoints"


def test_hideseek_search_waypoints_copied_not_aliased():
    bb, fsm = _bb_and_fsm()
    wps_in = ["X", "Y"]
    reconcile(
        {
            "target_state": "HIDEANDSEEK",
            "target_id": "c",
            "search_waypoints": wps_in,
            "play_area_key": "play_area",
        },
        fsm=fsm, blackboard=bb,
    )
    setters = {c.args[0]: c.args[1] for c in bb.set.call_args_list}
    stored = setters["search_waypoints"]
    assert stored == ["X", "Y"]
    wps_in.append("Z")
    assert stored == ["X", "Y"]


# 신규 — Task 8 추가

def test_hideseek_missing_play_area_key_rejected():
    bb, fsm = _bb_and_fsm()
    result = reconcile(
        {
            "target_state": "HIDEANDSEEK",
            "target_id": "child_5",
            "search_waypoints": ["patrol_a"],
            # play_area_key 누락
        },
        fsm=fsm, blackboard=bb,
    )
    assert result.accepted is False
    assert result.reason == "missing_play_area_key"


def test_hideseek_sets_play_area_blackboard():
    bb, fsm = _bb_and_fsm()
    result = reconcile(
        {
            "target_state": "HIDEANDSEEK",
            "target_id": "child_5",
            "search_waypoints": ["patrol_a", "patrol_b"],
            "play_area_key": "play_area",
        },
        fsm=fsm, blackboard=bb,
    )
    assert result.accepted is True
    setters = {c.args[0]: c.args[1] for c in bb.set.call_args_list}
    assert setters["hideseek_play_area_key"] == "play_area"


def test_hideseek_resets_registered_caught_phase_on_entry():
    """게임 다시 돌릴 때 이전 round 잔여물 reset 검증."""
    bb, fsm = _bb_and_fsm()
    result = reconcile(
        {
            "target_state": "HIDEANDSEEK",
            "target_id": "child_5",
            "search_waypoints": ["patrol_a"],
            "play_area_key": "play_area",
        },
        fsm=fsm, blackboard=bb,
    )
    assert result.accepted is True
    setters = {c.args[0]: c.args[1] for c in bb.set.call_args_list}
    # reset 3 키 모두 빈 값으로 셋
    assert setters["hideseek_registered_ids"] == []
    assert setters["hideseek_caught_ids"] == []
    assert setters["hideseek_phase"] == ""


def test_hideseek_resets_on_same_state_reentry():
    """current == target 인 재요청 (HIDEANDSEEK → HIDEANDSEEK) 도 reset 일어남 (다시 하기)."""
    bb, fsm = _bb_and_fsm(current="HIDEANDSEEK")
    result = reconcile(
        {
            "target_state": "HIDEANDSEEK",
            "target_id": "child_5",
            "search_waypoints": ["patrol_a"],
            "play_area_key": "play_area",
        },
        fsm=fsm, blackboard=bb,
    )
    assert result.accepted is True
    assert result.reason == "same_state"
    setters = {c.args[0]: c.args[1] for c in bb.set.call_args_list}
    assert setters["hideseek_caught_ids"] == []


# ---------------------------------------------------------------- MANUAL / RETURNING / IDLE

def test_manual_accepted():
    bb, fsm = _bb_and_fsm()
    result = reconcile({"target_state": "MANUAL"}, fsm=fsm, blackboard=bb)
    assert result.accepted is True
    assert result.trigger_fired == "manual_request"


def test_returning_accepted():
    bb, fsm = _bb_and_fsm()
    result = reconcile({"target_state": "RETURNING"}, fsm=fsm, blackboard=bb)
    assert result.accepted is True
    assert result.trigger_fired == "return_request"


def test_idle_from_active_uses_cancel():
    """active state 에서 IDLE 요청은 cancel trigger 로."""
    bb, fsm = _bb_and_fsm(current="GOTO")
    result = reconcile({"target_state": "IDLE"}, fsm=fsm, blackboard=bb)
    assert result.accepted is True
    assert result.trigger_fired == "cancel"


# ---------------------------------------------------------------- idempotent / lockdown

def test_same_state_is_idempotent():
    """이미 GOTO 인 상태에서 GOTO 재요청 — trigger 미발화, accepted=True."""
    bb, fsm = _bb_and_fsm(current="GOTO")
    result = reconcile(
        {"target_state": "GOTO", "destination_key": "X"},
        fsm=fsm, blackboard=bb,
    )
    assert result.accepted is True
    assert result.reason == "same_state"
    fsm.trigger.assert_not_called()
    # 그래도 destination_key 는 갱신 (같은 GOTO 안에서 새 destination 가능)
    setters = {c.args[0]: c.args[1] for c in bb.set.call_args_list}
    assert setters["destination_key"] == "X"


def test_charging_locks_out_user_command():
    bb, fsm = _bb_and_fsm(current="CHARGING")
    result = reconcile({"target_state": "GOTO", "destination_key": "X"}, fsm=fsm, blackboard=bb)
    assert result.accepted is False
    assert result.reason == "fsm_in_charging"
    fsm.trigger.assert_not_called()


def test_error_locks_out_all():
    bb, fsm = _bb_and_fsm(current="ERROR")
    result = reconcile({"target_state": "IDLE"}, fsm=fsm, blackboard=bb)
    assert result.accepted is False
    assert result.reason == "fsm_in_error_terminal"


def test_low_battery_return_locks_out_all():
    bb, fsm = _bb_and_fsm(current="LOW_BATTERY_RETURNING")
    result = reconcile({"target_state": "GOTO", "destination_key": "X"}, fsm=fsm, blackboard=bb)
    assert result.accepted is False
    assert result.reason == "fsm_in_low_battery_returning"
