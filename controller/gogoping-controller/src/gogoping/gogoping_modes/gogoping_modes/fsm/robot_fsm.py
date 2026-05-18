"""GogoPing 로봇 FSM — 8 states + 12 triggers.

명세: ``controller/gogoping-controller/docs/fsm-triggers.md``, ``docs/state-bt.md``.

- 8 states: ``CHARGING / IDLE / ASSIST / PLAY / MANUAL /
              RETURNING / LOW_BATTERY_RETURN / ERROR``
- 12 triggers: fsm-triggers.md 표 그대로

RETURNING vs LOW_BATTERY_RETURN — 둘 다 도크로 가는 도중이지만 정책 다름:
- **RETURNING**: 사용자 명시 (`return_request` / `idle_timeout`). CommandListener 살아있어 cancel / 새 task 명령 받음
- **LOW_BATTERY_RETURN**: 배터리 임계 자동 (`battery_low`). 명령 차단 — 충전소 도달까지 안전 우선

ERROR — **terminal**. 한번 들어가면 빠져나오는 transition 없음. 사람이 robot 재시작해야
복구. 사용자 명령 무시. 안전 우선 정책 (산업용 로봇 convention 일치).

- 블랙보드 부수효과 ("동시 작업" 컬럼) 는 호출자 책임 — 본 모듈은 순수 state machine.
  command_listener / monitor 가 trigger 발화 직전 blackboard 를 세팅한 뒤 ``fsm.trigger(...)``.

사용 예 (수동 검증)::

    fsm = RobotFSM()                               # initial="CHARGING"
    fsm.trigger("battery_full")                    # → IDLE
    fsm.trigger("assist_request", task="carry")    # → ASSIST
    fsm.trigger("battery_low")                     # → LOW_BATTERY_RETURN
    fsm.trigger("docked")                          # → CHARGING
    fsm.trigger("battery_full")                    # → IDLE
    fsm.trigger("manual_request")                  # → MANUAL  (torque OFF)
    fsm.trigger("cancel")                          # → IDLE   (torque ON 복귀)
    fsm.trigger("fault", reason="lidar_timeout")   # → ERROR  (terminal)
    fsm.trigger("assist_request", task="carry")    # → 무시 (ERROR 에서는 모든 명령 거부)

    fsm.add_callback("on_state_change", lambda: print(fsm.current_state))
"""
from __future__ import annotations

from typing import Callable

from transitions import Machine


STATES = [
    "CHARGING", "IDLE", "ASSIST", "PLAY", "MANUAL",
    "RETURNING", "LOW_BATTERY_RETURN", "ERROR",
]

# fault: 자동 감지 monitor 가 있는 state. ERROR 만 terminal 이라 제외.
# MANUAL 도 포함 — 사용자가 들고 옮기다 맵 경계 넘으면 nav2 가 path planning 불가
# 하므로 MapBoundaryMonitor 만 예외적으로 배치 (battery_low / hardware_health /
# collision 은 여전히 MANUAL 미배치, docs/bt/trees/BT_manual_main.md 정책 참조).
# LOW_BATTERY_RETURN 은 monitor (HW/Collision/MapBoundary) 있어 포함.
_FAULT_SOURCES = [
    "CHARGING", "IDLE", "ASSIST", "PLAY", "MANUAL",
    "RETURNING", "LOW_BATTERY_RETURN",
]
# 사용자 명시 복귀 명령 source — MANUAL 포함 (유저가 명령하면 torque ON + 도크 주행)
_RETURN_COMMAND_SOURCES = ["IDLE", "ASSIST", "PLAY", "MANUAL"]
# 배터리 모니터 자동 복귀 source — MANUAL 제외 (직접 미는 중 자동 빼앗기지 않음).
# RETURNING 포함 — 자발적 복귀 중에 배터리 critical 되면 escalation 으로 LOW_BATTERY_RETURN 진입.
_BATTERY_LOW_SOURCES = ["IDLE", "ASSIST", "PLAY", "RETURNING"]
# docked: 두 returning state 모두에서 도크 도달 시 CHARGING 으로
_DOCKED_SOURCES = ["RETURNING", "LOW_BATTERY_RETURN"]

TRANSITIONS = [
    # active-mode 진입 — IDLE 뿐 아니라 *다른 active mode* 에서도 직접 전이 가능.
    # 사용자가 ASSIST 중 PLAY 누르면 IDLE 경유 없이 BT swap 1회로 처리.
    # RETURNING (자발적 복귀) 도 source — 사용자가 복귀 중 마음 바꿔서 다른 명령 보내면 그쪽으로 전이.
    # terminate lifecycle 이 cleanup 보장 (ManualTorqueHold 의 torque ON 복원, BT_return_sub OneShot 정리 등).
    # LOW_BATTERY_RETURN 은 lockdown 이라 의도적으로 제외.
    {"trigger": "assist_request", "source": ["IDLE", "PLAY", "MANUAL", "RETURNING"],   "dest": "ASSIST"},
    {"trigger": "play_request",   "source": ["IDLE", "ASSIST", "MANUAL", "RETURNING"], "dest": "PLAY"},
    {"trigger": "manual_request", "source": ["IDLE", "ASSIST", "PLAY", "RETURNING"],   "dest": "MANUAL"},
    {"trigger": "battery_full",   "source": "CHARGING", "dest": "IDLE"},
    # ERROR 는 terminal — reset transition 없음. 사람이 robot 재시작해야 복구.
    {"trigger": "assist_done",    "source": "ASSIST",   "dest": "IDLE"},
    {"trigger": "play_done",      "source": "PLAY",     "dest": "IDLE"},
    # cancel: ASSIST/PLAY/MANUAL 의 "대기" 클릭 + RETURNING 도중 "대기" 로 복귀 취소.
    {"trigger": "cancel",         "source": ["ASSIST", "PLAY", "MANUAL", "RETURNING"], "dest": "IDLE"},
    {"trigger": "return_request", "source": _RETURN_COMMAND_SOURCES,      "dest": "RETURNING"},
    # battery_low 는 lockdown state 로. RETURNING (자발) 도 source 에 포함 — escalation.
    {"trigger": "battery_low",    "source": _BATTERY_LOW_SOURCES,         "dest": "LOW_BATTERY_RETURN"},
    {"trigger": "idle_timeout",   "source": "IDLE",                       "dest": "RETURNING"},
    {"trigger": "docked",         "source": _DOCKED_SOURCES,              "dest": "CHARGING"},
    {"trigger": "fault",          "source": _FAULT_SOURCES,               "dest": "ERROR"},
]

_TRIGGER_NAMES = frozenset(t["trigger"] for t in TRANSITIONS)


class RobotFSM:
    """8-state FSM.

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
        return self.state  # type: ignore[attr-defined]  # transitions.Machine 이 self.state 부여

    def trigger(self, name: str, **kwargs) -> bool:
        """trigger 발화. 성공 True / 무시 False. 알 수 없는 trigger 면 ValueError."""
        if name not in _TRIGGER_NAMES:
            raise ValueError(f"unknown trigger: {name!r}")
        method = getattr(self, name)
        return bool(method(**kwargs))

    def add_callback(self, event: str, fn: Callable[[], None]) -> None:
        """state 변경 콜백 등록. 현재 'on_state_change' 만 지원. fn() 은 무인자."""
        if event != "on_state_change":
            raise ValueError(f"unsupported event: {event!r}")
        self._listeners.append(fn)

    def _after_state_change(self, *args, **kwargs) -> None:
        for fn in self._listeners:
            fn()

    # ------------------------------------------------------------ debug

    def force_state(self, target: str) -> bool:
        """**디버그 전용** — transition 규칙 우회하고 state 강제 진입.

        admin UI 의 debug_state_bar (TopBar 디버그 row) 가 호출. 정상 운영에선 사용 X.

        - 모든 state 간 임의 전이 가능 (CHARGING / LOW_BATTERY_RETURN / ERROR 도 진입 가능)
        - ``on_state_change`` 콜백 정상 발화 → main.py 가 BT swap 처리
        - target 이 STATES 외면 False

        주의: transition library 의 callback API 가 직접 set_state 시 fire 되지 않으므로
        본 메서드가 수동으로 ``_after_state_change`` 호출.
        """
        if target not in STATES:
            return False
        old = self.current_state
        if old == target:
            return True  # no-op (이미 그 state)
        self.machine.set_state(target)
        # transitions.Machine.set_state 는 callback 안 부름 — 직접 호출
        self._after_state_change()
        return True
