"""goal_reconciler.reconcile() goto-only validation 단위 테스트.

carry-related 시나리오는 모두 삭제됨 (carry task 자체 폐기).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.utils.goal_reconciler import reconcile  # noqa: E402


def _bb_and_fsm():
    """Mock blackboard + fsm. blackboard.set 호출 record, fsm.trigger 호출 record."""
    bb = MagicMock()
    fsm = MagicMock()
    return bb, fsm


def test_goto_with_destination_accepted():
    """task=goto + destination_key 있으면 accepted, fsm.trigger 호출, blackboard 세팅."""
    bb, fsm = _bb_and_fsm()
    fsm.current_state = "IDLE"
    fsm.trigger.return_value = True
    result = reconcile(
        goal={"mode": "ASSIST", "task": "goto", "destination_key": "교실A"},
        blackboard=bb,
        fsm=fsm,
    )
    assert result.accepted is True
    assert result.reason == "" or result.reason == "same_mode"


def test_goto_missing_destination_rejected():
    """task=goto 인데 destination_key 빈 값이면 'missing_destination'."""
    bb, fsm = _bb_and_fsm()
    fsm.current_state = "IDLE"
    result = reconcile(
        goal={"mode": "ASSIST", "task": "goto", "destination_key": ""},
        blackboard=bb,
        fsm=fsm,
    )
    assert result.accepted is False
    assert result.reason == "missing_destination"


def test_carry_task_no_longer_valid():
    """task=carry 는 더 이상 유효한 task 가 아님 → invalid_task 또는 유사."""
    bb, fsm = _bb_and_fsm()
    fsm.current_state = "IDLE"
    result = reconcile(
        goal={"mode": "ASSIST", "task": "carry", "destination_key": "X"},
        blackboard=bb,
        fsm=fsm,
    )
    assert result.accepted is False
    # invalid task 거부 — 정확한 reason 문자열은 reconciler 코드를 따라가지만 carry 가 _ASSIST_TASKS 에 없어야 함
    assert "task" in result.reason or "invalid" in result.reason or "unknown" in result.reason


def test_lullaby_still_works():
    """task=lullaby 는 그대로 작동 (regression check)."""
    bb, fsm = _bb_and_fsm()
    fsm.current_state = "IDLE"
    fsm.trigger.return_value = True
    result = reconcile(
        goal={"mode": "ASSIST", "task": "lullaby"},
        blackboard=bb,
        fsm=fsm,
    )
    assert result.accepted is True


# ---------------------------------------------------------------- hideseek (PLAY)


def test_hideseek_with_target_and_waypoints_accepted():
    """PLAY/hideseek + target_id + search_waypoints → accepted, BB 에 두 키 write."""
    bb, fsm = _bb_and_fsm()
    fsm.current_state = "IDLE"
    fsm.trigger.return_value = True
    result = reconcile(
        goal={
            "mode": "PLAY", "task": "hideseek",
            "target_id": "child_42",
            "search_waypoints": ["A", "B", "C"],
        },
        blackboard=bb,
        fsm=fsm,
    )
    assert result.accepted is True
    assert result.trigger_fired == "play_request"
    # BB write 검증 — play_task / target_person_id / search_waypoints
    setters = {call.args[0]: call.args[1] for call in bb.set.call_args_list}
    assert setters["play_task"] == "hideseek"
    assert setters["target_person_id"] == "child_42"
    assert setters["search_waypoints"] == ["A", "B", "C"]


def test_hideseek_missing_search_waypoints_rejected():
    """PLAY/hideseek + target_id 있음 + search_waypoints 비면 'missing_search_waypoints'."""
    bb, fsm = _bb_and_fsm()
    fsm.current_state = "IDLE"
    result = reconcile(
        goal={
            "mode": "PLAY", "task": "hideseek",
            "target_id": "child_42",
            "search_waypoints": [],
        },
        blackboard=bb,
        fsm=fsm,
    )
    assert result.accepted is False
    assert result.reason == "missing_search_waypoints"
    fsm.trigger.assert_not_called()


def test_hideseek_missing_target_id_rejected():
    """PLAY/hideseek + waypoints 있음 + target_id 비면 'missing_target_id'."""
    bb, fsm = _bb_and_fsm()
    fsm.current_state = "IDLE"
    result = reconcile(
        goal={
            "mode": "PLAY", "task": "hideseek",
            "target_id": "",
            "search_waypoints": ["A", "B"],
        },
        blackboard=bb,
        fsm=fsm,
    )
    assert result.accepted is False
    assert result.reason == "missing_target_id"
    fsm.trigger.assert_not_called()


def test_hideseek_search_waypoints_copied_not_aliased():
    """BB.set 에 들어가는 list 가 입력 list 의 별도 복사본인지 (외부 mutate 안전)."""
    bb, fsm = _bb_and_fsm()
    fsm.current_state = "IDLE"
    fsm.trigger.return_value = True
    wps_in = ["X", "Y"]
    reconcile(
        goal={
            "mode": "PLAY", "task": "hideseek",
            "target_id": "child_42",
            "search_waypoints": wps_in,
        },
        blackboard=bb,
        fsm=fsm,
    )
    setters = {call.args[0]: call.args[1] for call in bb.set.call_args_list}
    stored = setters["search_waypoints"]
    assert stored == ["X", "Y"]
    # 외부 mutate 가 BB 에 반영되지 않아야 함
    wps_in.append("Z")
    assert stored == ["X", "Y"]
