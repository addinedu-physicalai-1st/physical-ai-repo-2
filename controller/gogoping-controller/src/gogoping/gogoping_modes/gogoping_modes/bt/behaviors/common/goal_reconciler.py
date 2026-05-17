"""Goal reconciler — UI 가 보낸 Goal 을 현재 FSM 상태와 비교해 trigger 발화.

본 모듈은 **순수 Python** — ROS / py_trees 의존성 없음. 따라서:
- 단위 테스트 가능 (ROS sourcing 불필요)
- ``command_listener.py`` (py_trees behavior + ROS srv server) 가 본 함수를 wrap
- robot-web 디버그 / 데모용 CLI 도 같은 로직 재사용 가능

## Goal-based 디자인 요약

UI 는 trigger 이름 (assist_command, manual_command, ...) 을 모른다. 대신
"원하는 mode" 만 알려주면 (Goal.msg 의 ``mode`` 필드) 본 함수가 현재 state 와 비교해
적절한 trigger 를 발화한다. 자세한 배경: ``docs/fsm-triggers.md`` 의 머리말 노트.

## reconcile() 의 책임

1. Goal validation — mode / task 조합이 valid 한지
2. blackboard 세팅 — assist_task / play_task / carry_mode / destination_key / target_id
3. FSM trigger 발화 — current_state ↔ desired mode 차이에 따라

invalid goal 은 ``ReconcileResult(accepted=False, reason="...")`` 반환 — trigger 미발화.

## current_state 와 동일 mode 재요청

idempotent — trigger 미발화 + accepted=True 반환. blackboard 의 task / carry_mode /
destination_key / target_id 는 *덮어쓸 수도* 있고 *유지할 수도* 있다 (지금은 덮어씀 —
같은 ASSIST 안에서 carry → follow 미세 전환 가능).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


# ---------------------------------------------------------------- Protocols


class _FSMProto(Protocol):
    """RobotFSM 의 reconciler 가 의존하는 표면만 — 단위 테스트에서 mock 가능."""

    @property
    def current_state(self) -> str: ...
    def trigger(self, name: str, **kwargs: Any) -> bool: ...


class _BlackboardProto(Protocol):
    """py_trees Blackboard Client 또는 simple dict-set 호환 객체."""

    def set(self, key: str, value: Any) -> None: ...


# ---------------------------------------------------------------- Result


@dataclass(frozen=True)
class ReconcileResult:
    """``SetGoal.srv`` response 와 매핑되는 reconcile 결과.

    ``trigger_fired`` 는 디버깅 / 테스트용 — 실제 ROS response 에는 안 들어감.
    """

    accepted: bool
    reason: str = ""
    trigger_fired: str | None = None


# ---------------------------------------------------------------- Constants

_VALID_MODES = ("IDLE", "ASSIST", "PLAY", "MANUAL", "RETURNING")

_ASSIST_TASKS = ("carry", "follow", "lullaby")
_PLAY_TASKS = ("hideseek",)
_CARRY_MODES = ("manual", "goto", "follow")


# ---------------------------------------------------------------- Blackboard keys
# (string literal — bt/blackboard.py 의 Keys 와 일치. 순환 import 회피 위해 직접 박음.
#  Keys 가 바뀌면 본 파일도 같이 — docs/blackboard-schema.md 가 spec)

_K_ASSIST_TASK = "assist_task"
_K_PLAY_TASK = "play_task"
_K_CARRY_MODE = "carry_mode"
_K_DESTINATION_KEY = "destination_key"
_K_TARGET_PERSON_ID = "target_person_id"


# ---------------------------------------------------------------- Validation


def _validate(goal: dict) -> str | None:
    """invalid goal 의 reason 문자열 반환. valid 면 None.

    ``SetGoal.srv`` 의 response.reason 으로 그대로 사용 가능 — 자세한 코드 매핑은
    ``gogoping_msgs/srv/SetGoal.srv`` 의 주석.
    """
    mode = goal.get("mode", "")
    if mode not in _VALID_MODES:
        return "invalid_mode"

    if mode in ("ASSIST", "PLAY"):
        task = goal.get("task", "")
        if not task:
            return "missing_task"
        if mode == "ASSIST" and task not in _ASSIST_TASKS:
            return "invalid_task_for_mode"
        if mode == "PLAY" and task not in _PLAY_TASKS:
            return "invalid_task_for_mode"

        # 추가 필드 검증
        if mode == "ASSIST" and task == "carry":
            carry_mode = goal.get("carry_mode", "")
            if not carry_mode:
                return "missing_carry_mode"
            if carry_mode not in _CARRY_MODES:
                return "invalid_carry_mode"
            if carry_mode == "goto" and not goal.get("destination_key"):
                return "missing_destination"
            if carry_mode == "follow" and not goal.get("target_id"):
                return "missing_target_id"

        if mode == "ASSIST" and task == "follow" and not goal.get("target_id"):
            return "missing_target_id"

        if mode == "PLAY" and task == "hideseek" and not goal.get("target_id"):
            return "missing_target_id"

    return None


# ---------------------------------------------------------------- Main entry


def reconcile(
    goal: dict,
    fsm: _FSMProto,
    blackboard: _BlackboardProto,
) -> ReconcileResult:
    """UI 가 보낸 goal 을 받아 적절한 FSM trigger 발화.

    Parameters
    ----------
    goal : dict
        ``Goal.msg`` 의 필드 — ``mode`` / ``task`` / ``carry_mode`` /
        ``destination_key`` / ``target_id``. 빠진 필드는 빈 문자열로 간주.
    fsm : RobotFSM-like
        ``current_state`` property + ``trigger(name, **kwargs)`` method 노출.
    blackboard : Blackboard-like
        ``set(key, value)`` method 노출. py_trees Client 또는 dict wrapper.

    Returns
    -------
    ReconcileResult
        ``accepted=True`` 면 (trigger 발화했거나 idempotent no-op). ``False`` 면
        validation 실패 — ``reason`` 에 사유.
    """
    err = _validate(goal)
    if err is not None:
        return ReconcileResult(accepted=False, reason=err)

    mode = goal["mode"]
    current = fsm.current_state

    # 1) 같은 mode 재요청 — idempotent. blackboard 의 task 관련 키는 갱신 (carry → follow 전환).
    if current == mode:
        _set_task_blackboard(goal, blackboard)
        return ReconcileResult(accepted=True, reason="same_mode")

    # 2) CHARGING / ERROR 는 desired 로 발행 불가 케이스 따로
    if current == "CHARGING":
        # 사용자 직접 명령으로는 CHARGING 이탈 불가 — battery_full monitor 만 가능
        return ReconcileResult(accepted=False, reason="fsm_in_charging")
    if current == "ERROR":
        if mode == "IDLE":
            # reset trigger 로 ERROR → IDLE
            ok = fsm.trigger("reset")
            return ReconcileResult(
                accepted=ok, reason="" if ok else "reset_failed", trigger_fired="reset" if ok else None,
            )
        return ReconcileResult(accepted=False, reason="fsm_in_error")

    # 3) 일반적인 desired mode 매핑
    if mode == "IDLE":
        # ASSIST/PLAY/MANUAL → IDLE 은 cancel 로
        ok = fsm.trigger("cancel")
        # 취소했으면 task 키 초기화
        if ok:
            blackboard.set(_K_ASSIST_TASK, "")
            blackboard.set(_K_PLAY_TASK, "")
        return ReconcileResult(
            accepted=ok, trigger_fired="cancel" if ok else None,
        )

    if mode == "RETURNING":
        ok = fsm.trigger("return_command")
        return ReconcileResult(
            accepted=ok, trigger_fired="return_command" if ok else None,
        )

    if mode == "ASSIST":
        _set_task_blackboard(goal, blackboard)
        ok = fsm.trigger("assist_command", task=goal["task"])
        return ReconcileResult(
            accepted=ok, trigger_fired="assist_command" if ok else None,
        )

    if mode == "PLAY":
        _set_task_blackboard(goal, blackboard)
        ok = fsm.trigger("play_command", task=goal["task"])
        return ReconcileResult(
            accepted=ok, trigger_fired="play_command" if ok else None,
        )

    if mode == "MANUAL":
        ok = fsm.trigger("manual_command")
        return ReconcileResult(
            accepted=ok, trigger_fired="manual_command" if ok else None,
        )

    # 도달 불가 — validate 가 잡았어야 함
    return ReconcileResult(accepted=False, reason="unhandled_mode")


# ---------------------------------------------------------------- Helpers


def _set_task_blackboard(goal: dict, blackboard: _BlackboardProto) -> None:
    """ASSIST / PLAY 시 task / carry_mode / destination_key / target_id 를 blackboard 에."""
    mode = goal["mode"]
    task = goal.get("task", "")

    if mode == "ASSIST":
        blackboard.set(_K_ASSIST_TASK, task)
        if task == "carry":
            blackboard.set(_K_CARRY_MODE, goal.get("carry_mode", ""))
            blackboard.set(_K_DESTINATION_KEY, goal.get("destination_key", ""))
            blackboard.set(_K_TARGET_PERSON_ID, goal.get("target_id", ""))
        elif task == "follow":
            blackboard.set(_K_TARGET_PERSON_ID, goal.get("target_id", ""))
        # lullaby 는 추가 키 없음
    elif mode == "PLAY":
        blackboard.set(_K_PLAY_TASK, task)
        if task == "hideseek":
            blackboard.set(_K_TARGET_PERSON_ID, goal.get("target_id", ""))


__all__ = ["ReconcileResult", "reconcile"]
