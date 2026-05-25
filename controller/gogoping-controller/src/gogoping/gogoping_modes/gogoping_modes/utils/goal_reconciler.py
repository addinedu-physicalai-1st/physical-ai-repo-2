"""Goal reconciler — UI 가 보낸 Goal 을 현재 FSM 상태와 비교해 trigger 발화.

평탄화 (2026-05-25): target_state 직접 매핑. mode/task 두 축 제거.

순수 Python — ROS / py_trees 의존성 없음. 단위 테스트 가능.

## 책임

1. target_state validation — 7개 외부 가능 state 중 하나인지
2. body 필드 validation — GOTO 면 destination_key, FOLLOW/HIDEANDSEEK 면 target_id 등
3. blackboard 세팅 — destination_key / target_person_id / search_waypoints
4. FSM trigger 발화 — current_state → desired target_state 매핑

## current_state == target_state 재요청

idempotent — trigger 미발화 + accepted=True. body 필드 (destination_key 등) 는 덮어씀.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class _FSMProto(Protocol):
    @property
    def current_state(self) -> str: ...
    def trigger(self, name: str, **kwargs: Any) -> bool: ...


class _BlackboardProto(Protocol):
    def set(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True)
class ReconcileResult:
    accepted: bool
    reason: str = ""
    trigger_fired: str | None = None


# 외부에서 SetGoal.srv 로 요청 가능한 state.
# CHARGING / LOW_BATTERY_RETURNING / ERROR 는 내부 trigger 전용.
_EXTERNAL_STATES = frozenset({
    "IDLE", "GOTO", "FOLLOW", "LULLABY", "HIDEANDSEEK", "MANUAL", "RETURNING",
})
_INTERNAL_ONLY = frozenset({"CHARGING", "LOW_BATTERY_RETURNING", "ERROR"})

# target_state → trigger 이름 매핑 (active 진입).
_REQUEST_TRIGGER = {
    "GOTO":        "goto_request",
    "FOLLOW":      "follow_request",
    "LULLABY":     "lullaby_request",
    "HIDEANDSEEK": "hideseek_request",
    "MANUAL":      "manual_request",
    "RETURNING":   "return_request",
}

# blackboard 키 string (bt/blackboard.py Keys 와 일치).
_K_DESTINATION_KEY = "destination_key"
_K_TARGET_PERSON_ID = "target_person_id"
_K_SEARCH_WAYPOINTS = "search_waypoints"
_K_HIDESEEK_PLAY_AREA = "hideseek_play_area_key"
_K_HIDESEEK_REGISTERED_IDS = "hideseek_registered_ids"
_K_HIDESEEK_CAUGHT_IDS = "hideseek_caught_ids"
_K_HIDESEEK_PHASE = "hideseek_phase"


def _validate(goal: dict) -> str | None:
    """invalid 사유 string, valid 면 None."""
    target = goal.get("target_state", "")
    if target not in _EXTERNAL_STATES and target not in _INTERNAL_ONLY:
        return "invalid_target_state"
    if target in _INTERNAL_ONLY:
        return "internal_only_state"

    if target == "GOTO" and not goal.get("destination_key"):
        return "missing_destination"
    if target == "FOLLOW" and not goal.get("target_id"):
        return "missing_target_id"
    if target == "HIDEANDSEEK":
        if not goal.get("target_id"):
            return "missing_target_id"
        if not goal.get("search_waypoints"):
            return "missing_search_waypoints"
        if not goal.get("play_area_key"):
            return "missing_play_area_key"
    return None


def reconcile(
    goal: dict,
    fsm: _FSMProto,
    blackboard: _BlackboardProto,
) -> ReconcileResult:
    """target_state 기반 goal 처리."""
    err = _validate(goal)
    if err is not None:
        return ReconcileResult(accepted=False, reason=err)

    target = goal["target_state"]
    current = fsm.current_state

    # 같은 state 재요청 — idempotent. body 필드만 갱신.
    if current == target:
        _set_body_blackboard(goal, blackboard)
        return ReconcileResult(accepted=True, reason="same_state")

    # lockdown — 현재 state 가 명령 거부.
    if current == "CHARGING":
        return ReconcileResult(accepted=False, reason="fsm_in_charging")
    if current == "ERROR":
        return ReconcileResult(accepted=False, reason="fsm_in_error_terminal")
    if current == "LOW_BATTERY_RETURNING":
        return ReconcileResult(accepted=False, reason="fsm_in_low_battery_returning")

    # IDLE 요청 — active state 면 cancel.
    if target == "IDLE":
        ok = fsm.trigger("cancel")
        return ReconcileResult(
            accepted=ok, trigger_fired="cancel" if ok else None,
        )

    # active state 진입.
    _set_body_blackboard(goal, blackboard)
    trigger_name = _REQUEST_TRIGGER[target]
    ok = fsm.trigger(trigger_name)
    return ReconcileResult(
        accepted=ok, trigger_fired=trigger_name if ok else None,
    )


def _set_body_blackboard(goal: dict, blackboard: _BlackboardProto) -> None:
    """target_state 에 따라 destination_key / target_id / search_waypoints 세팅."""
    target = goal["target_state"]
    if target == "GOTO":
        blackboard.set(_K_DESTINATION_KEY, goal.get("destination_key", ""))
    elif target == "FOLLOW":
        blackboard.set(_K_TARGET_PERSON_ID, goal.get("target_id", ""))
    elif target == "HIDEANDSEEK":
        blackboard.set(_K_TARGET_PERSON_ID, goal.get("target_id", ""))
        blackboard.set(_K_SEARCH_WAYPOINTS, list(goal.get("search_waypoints", [])))
        blackboard.set(_K_HIDESEEK_PLAY_AREA, goal.get("play_area_key", ""))
        # 같은 게임을 다시 돌릴 때 이전 round 의 registered/caught/phase 가 남아
        # AwaitRecruitComplete 가 즉시 SUCCESS 되거나 CaughtMonitor 가 즉시 SUCCESS
        # 되어 게임이 진행되지 않는 것을 막는다. HIDEANDSEEK 진입 시마다 reset.
        blackboard.set(_K_HIDESEEK_REGISTERED_IDS, [])
        blackboard.set(_K_HIDESEEK_CAUGHT_IDS, [])
        blackboard.set(_K_HIDESEEK_PHASE, "")


__all__ = ["ReconcileResult", "reconcile"]
