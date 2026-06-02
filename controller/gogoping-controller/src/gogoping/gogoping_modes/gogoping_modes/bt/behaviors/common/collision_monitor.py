"""CollisionMonitor — nav2 collision_monitor 가 cmd_vel 을 stop 으로 끊은 상태가
5분 이상 지속되면 FSM trigger 발화.

데이터 plane(nav2 collision_monitor 노드)이 LiDAR stop zone 으로 실제 정지를 담당하고,
본 leaf 는 그 stop 이 **장시간 풀리지 않을 때**의 상위 반응을 담당한다:
- LOW_BATTERY_RETURNING → ``fault`` (→ ERROR). 방전 위험이라 IDLE 로 방치하지 않고
  교사 호출. (LOW_BATTERY 는 FSM lockdown — cancel 거부, fault 만 받음.)
- 그 외 주행 state (GOTO / RETURNING / HIDEANDSEEK) → ``cancel`` (→ IDLE). task 포기.

``COLLISION_STATE`` 는 ``collision_subscriber`` 가 collision_monitor 의 state 토픽에서
``"ok"`` / ``"stop"`` 으로 갱신한다.

배치 (``_shell.py`` include_collision): GOTO / RETURNING / LOW_BATTERY_RETURNING /
HIDEANDSEEK (움직이는 state). FOLLOW 는 제외 — 사람 추종(REACTIVE)은 nav2 controller 를
거치지 않아 collision_monitor 게이팅 대상이 아니고, 가까운 사람을 막으면 안 되기 때문.

monitor 컨벤션 (``docs/conventions.md`` §2):
- 매 tick RUNNING.
- edge-triggered — 1회 발화 후 state 전이(IDLE/ERROR)되므로 re-arm 불필요.
  ``initialise()`` 가 새 트리 진입 시 타이머/플래그 리셋.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional, Tuple

import py_trees
from py_trees.common import Access, Status

from ...blackboard import Keys
from ....utils.safety_flags import is_safety_disabled

if TYPE_CHECKING:
    from ....context import Context


COLLISION_STOP = "stop"
_DEFAULT_TIMEOUT_S = 300.0   # 5분
_REASON = "collision_stuck"


def timeout_trigger_for_state(state: str) -> str:
    """5분 stuck 시 발화할 FSM trigger.

    LOW_BATTERY_RETURNING 은 lockdown + 방전 위험 → ``fault``(ERROR).
    그 외 주행 state 는 ``cancel``(IDLE).
    """
    return "fault" if state == "LOW_BATTERY_RETURNING" else "cancel"


def evaluate_collision_timeout(
    collision_state: str,
    stop_since: Optional[float],
    now: float,
    current_state: str,
    timeout_s: float,
) -> Tuple[Optional[float], Optional[str]]:
    """stop 지속 타이머 + 발화 판단 (pure).

    Returns ``(new_stop_since, trigger)``:
      - stop 이 아니면 ``(None, None)`` — 타이머 리셋.
      - stop 시작 tick → ``(now, None)``.
      - stop 지속 < timeout → ``(started, None)``.
      - stop 지속 >= timeout → ``(started, "cancel"|"fault")``.
    """
    if collision_state != COLLISION_STOP:
        return (None, None)
    started = stop_since if stop_since is not None else now
    if now - started >= timeout_s:
        return (started, timeout_trigger_for_state(current_state))
    return (started, None)


class CollisionMonitor(py_trees.behaviour.Behaviour):
    """COLLISION_STATE == "stop" 가 5분 지속되면 cancel/fault 발화."""

    def __init__(self, name: str, context: "Context", timeout_s: float = _DEFAULT_TIMEOUT_S):
        super().__init__(name)
        self.ctx = context
        self._timeout_s = float(timeout_s)
        self.bb = self.attach_blackboard_client(name=name)
        self.bb.register_key(key=Keys.COLLISION_STATE, access=Access.READ)
        self.bb.register_key(key=Keys.ERROR_REASON, access=Access.WRITE)
        self.bb.register_key(key=Keys.ERROR_SOURCE, access=Access.WRITE)
        self._stop_since: Optional[float] = None
        self._fired = False
        self._disabled = is_safety_disabled(
            getattr(self.ctx, "node", None), "error", monitor_name=self.name,
        )

    def initialise(self) -> None:
        # 새 트리 진입 시 타이머/플래그 리셋 — 다른 state 재진입 시 다시 동작.
        self._stop_since = None
        self._fired = False

    def update(self) -> Status:
        if self._disabled or self._fired:
            return Status.RUNNING

        try:
            state = str(self.bb.get(Keys.COLLISION_STATE))
        except (KeyError, TypeError):
            state = "ok"

        self._stop_since, trigger = evaluate_collision_timeout(
            collision_state=state,
            stop_since=self._stop_since,
            now=time.monotonic(),
            current_state=self.ctx.fsm.current_state,
            timeout_s=self._timeout_s,
        )
        if trigger is not None:
            if trigger == "fault":
                self.bb.set(Keys.ERROR_REASON, _REASON)
                self.bb.set(Keys.ERROR_SOURCE, self.name)
            self.ctx.fsm.trigger(trigger, reason=_REASON)
            self._fired = True

        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        # idempotent — 별도 cleanup 없음
        pass
