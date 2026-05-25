"""GogoPing 로봇 FSM — 10 states + 13 triggers.

명세: ``controller/gogoping-controller/docs/fsm-triggers.md``, ``docs/state-bt.md``.

- 10 states: ``IDLE / CHARGING / GOTO / FOLLOW / LULLABY / HIDEANDSEEK /
              MANUAL / RETURNING / LOW_BATTERY_RETURNING / ERROR``
- 13 triggers: fsm-triggers.md 표 그대로

평탄화 (refactoring-state 브랜치, 2026-05-25):
- 기존 ASSIST / PLAY 그룹 제거. sub-task (goto/follow/lullaby/hideseek) 가 1급 state 로 격상.
- assist_done / play_done → task_done 으로 통합.
- assist_request / play_request → goto_request / follow_request / lullaby_request / hideseek_request 로 분기.

특수 정책:
- **MANUAL**: battery_low / idle_timeout / task_done monitor 미배치. 사용자 직접 명령으로만 이탈.
- **LOW_BATTERY_RETURNING**: lockdown — docked / fault 만 받음. 사용자 명령 전체 거부.
- **ERROR**: terminal — 어떤 trigger 도 받지 않음. robot 재시작만 복구.
- **CHARGING → IDLE**: battery_full monitor 자동 전이만. 사용자 직접 명령 불가.
- **active ↔ active**: GOTO/FOLLOW/LULLABY/HIDEANDSEEK/MANUAL/RETURNING 간 직접 전이 가능 (IDLE 경유 불필요).

블랙보드 부수효과 (destination_key / target_id 등) 는 호출자 책임 — 본 모듈은 순수 state machine.
"""
from __future__ import annotations

from typing import Callable

from transitions import Machine


STATES = [
    "IDLE", "CHARGING", "GOTO", "FOLLOW", "LULLABY", "HIDEANDSEEK",
    "MANUAL", "RETURNING", "LOW_BATTERY_RETURNING", "ERROR",
]

# 활성 task state — 사용자가 명령으로 진입/이탈 가능한 작업 단위.
_TASK_STATES = ["GOTO", "FOLLOW", "LULLABY", "HIDEANDSEEK"]
# 사용자 명령 가능한 source — IDLE + 4 task + MANUAL + RETURNING (= 7).
_USER_COMMAND_SOURCES = ["IDLE"] + _TASK_STATES + ["MANUAL", "RETURNING"]

# fault: ERROR 외 모두에서 발화 가능 (terminal 진입).
_FAULT_SOURCES = [s for s in STATES if s != "ERROR"]

# return_request: 사용자 명시 — MANUAL 도 포함.
_RETURN_COMMAND_SOURCES = ["IDLE"] + _TASK_STATES + ["MANUAL"]
# battery_low: MANUAL 제외 — 사용자 직접 제어 중 자동 빼앗기 금지.
_BATTERY_LOW_SOURCES = ["IDLE"] + _TASK_STATES + ["RETURNING"]
# docked: 두 returning state 모두에서 도크 도달 시 CHARGING.
_DOCKED_SOURCES = ["RETURNING", "LOW_BATTERY_RETURNING"]
# cancel: 4 task + MANUAL + RETURNING → IDLE.
_CANCEL_SOURCES = _TASK_STATES + ["MANUAL", "RETURNING"]


def _request_sources_excluding(dest: str) -> list[str]:
    """task_request / manual_request 의 source list — dest 자신 제외."""
    return [s for s in _USER_COMMAND_SOURCES if s != dest]


TRANSITIONS = [
    # CHARGING → IDLE
    {"trigger": "battery_full",    "source": "CHARGING",                                  "dest": "IDLE"},
    # task_request — active state 끼리 직접 전이 OK (자기 자신 제외).
    {"trigger": "goto_request",    "source": _request_sources_excluding("GOTO"),          "dest": "GOTO"},
    {"trigger": "follow_request",  "source": _request_sources_excluding("FOLLOW"),        "dest": "FOLLOW"},
    {"trigger": "lullaby_request", "source": _request_sources_excluding("LULLABY"),       "dest": "LULLABY"},
    {"trigger": "hideseek_request","source": _request_sources_excluding("HIDEANDSEEK"),   "dest": "HIDEANDSEEK"},
    {"trigger": "manual_request",  "source": _request_sources_excluding("MANUAL"),        "dest": "MANUAL"},
    {"trigger": "return_request",  "source": _RETURN_COMMAND_SOURCES,                     "dest": "RETURNING"},
    # cancel
    {"trigger": "cancel",          "source": _CANCEL_SOURCES,                             "dest": "IDLE"},
    # task body 정상 완료 — MainTree root SUCCESS 감지 시 main.py 가 발화.
    {"trigger": "task_done",       "source": _TASK_STATES,                                "dest": "IDLE"},
    # 자동 monitor
    {"trigger": "battery_low",     "source": _BATTERY_LOW_SOURCES,                        "dest": "LOW_BATTERY_RETURNING"},
    {"trigger": "idle_timeout",    "source": "IDLE",                                      "dest": "RETURNING"},
    {"trigger": "docked",          "source": _DOCKED_SOURCES,                             "dest": "CHARGING"},
    {"trigger": "fault",           "source": _FAULT_SOURCES,                              "dest": "ERROR"},
]

_TRIGGER_NAMES = frozenset(t["trigger"] for t in TRANSITIONS)


class RobotFSM:
    """10-state FSM.

    - ``trigger(name, **kwargs)`` 는 idempotent: 현재 state 에서 invalid 면 silently False.
    - state 전이 발생 시 등록된 ``on_state_change`` 콜백을 무인자로 호출 (main.py 의 BT swap 훅).
    - ERROR 는 terminal — 어떤 trigger 도 받지 않음.
    """

    def __init__(self, initial: str = "CHARGING"):
        if initial not in STATES:
            raise ValueError(f"invalid initial state: {initial}")
        self._listeners: list[Callable[[], None]] = []
        self.machine = Machine(
            model=self,
            states=STATES,
            transitions=TRANSITIONS,
            initial=initial,
            auto_transitions=False,
            ignore_invalid_triggers=True,
            after_state_change="_after_state_change",
        )

    @property
    def current_state(self) -> str:
        return self.state  # type: ignore[attr-defined]

    def trigger(self, name: str, **kwargs) -> bool:
        if name not in _TRIGGER_NAMES:
            raise ValueError(f"unknown trigger: {name!r}")
        method = getattr(self, name)
        return bool(method(**kwargs))

    def add_callback(self, event: str, fn: Callable[[], None]) -> None:
        if event != "on_state_change":
            raise ValueError(f"unsupported event: {event!r}")
        self._listeners.append(fn)

    def _after_state_change(self, *args, **kwargs) -> None:
        for fn in self._listeners:
            fn()

    def force_state(self, target: str) -> bool:
        """디버그 전용 — transition 규칙 우회."""
        if target not in STATES:
            return False
        old = self.current_state
        if old == target:
            return True
        self.machine.set_state(target)
        self._after_state_change()
        return True
