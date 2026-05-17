"""BatteryFullMonitor — blackboard.BATTERY_LEVEL ≥ 80% 시 ``battery_full`` 발화.

CHARGING state MainTree 에 들어가는 monitor — 충전이 끝나면 자동으로 IDLE 로 전이.

monitor 컨벤션 (``docs/conventions.md`` §2):
- 매 tick RUNNING 리턴 (SUCCESS / FAILURE 금지)
- edge-triggered — 직전 값과 비교, 같은 trigger 매 tick 반복 호출 안 함
- 진입 시 `_fired = False` 로 초기화 (re-entry 시 재발화 가능)

현재 단계엔 ``BatterySubscriber`` 가 stub 이라 BATTERY_LEVEL 이
``blackboard.init_blackboard()`` 의 기본값 100.0 으로 고정. 즉 부팅 시 첫 tick 에
``battery_full`` 발화 → CHARGING → IDLE 즉시 전이. 사용자 의도 ("부팅 = CHARGING,
배터리 정상이면 IDLE") 시퀀스 그대로.

추후 ``BatterySubscriber`` 가 실제 ROS 토픽 구독으로 교체되면 자연스럽게 진짜 배터리
값에 따라 동작.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Access, Status

from ...blackboard import Keys

if TYPE_CHECKING:
    from ....context import Context


class BatteryFullMonitor(py_trees.behaviour.Behaviour):
    """배터리 ≥ 70% 시 ``battery_full`` FSM trigger 발화."""

    FULL_ENTER = 70.0  # 진입 임계 (%)

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context
        self.bb = self.attach_blackboard_client(name=name)
        self.bb.register_key(key=Keys.BATTERY_LEVEL, access=Access.READ)
        self._fired = False

    def initialise(self) -> None:
        # 트리 swap 시 (CHARGING re-entry) 다시 발화 가능하게.
        self._fired = False

    def update(self) -> Status:
        if not self._fired:
            try:
                level = float(self.bb.get(Keys.BATTERY_LEVEL))
            except (KeyError, TypeError, ValueError):
                return Status.RUNNING
            if level >= self.FULL_ENTER:
                self._fired = True
                self.ctx.fsm.trigger("battery_full")
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        # idempotent — 별도 cleanup 없음
        pass
