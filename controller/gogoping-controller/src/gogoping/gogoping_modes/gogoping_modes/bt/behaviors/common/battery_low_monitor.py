"""BatteryLowMonitor — blackboard.BATTERY_LEVEL ≤ 15% 시 ``battery_low`` 발화.

IDLE / ASSIST / PLAY / RETURNING MainTree 에 들어가는 monitor.
- IDLE / ASSIST / PLAY → RETURNING (자동 도크 복귀)
- RETURNING → LOW_BATTERY_RETURNING (escalation — 도크로 가는 도중에 또 떨어지면 lockdown)
- MANUAL 의도적 미배치 — 사용자가 들고 있는데 자동 빼앗김 방지 (``docs/state-bt.md`` 참조)

monitor 컨벤션 (``docs/conventions.md`` §2):
- 매 tick RUNNING 리턴 (SUCCESS / FAILURE 금지)
- edge-triggered + hysteresis — 15% 진입 fire, 25% 진출 reset (chattering 방지)
- ``initialise()`` 에서 ``_fired = False`` 리셋 — 트리 swap 후 재진입 시 재발화 가능

추후 ``BatterySubscriber`` 가 실제 ROS 토픽 구독으로 교체되면 자연스럽게 진짜 배터리
값에 따라 동작. 현재는 ``sim_battery_node`` + ``/gogoping/sim/set_battery_level`` srv
로 admin UI 슬라이더에서 임의 값 강제 → 자동 RETURNING / LOW_BATTERY_RETURNING escalation
검증 가능.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Access, Status

from ...blackboard import Keys
from ....utils.safety_flags import is_safety_disabled

if TYPE_CHECKING:
    from ....context import Context


class BatteryLowMonitor(py_trees.behaviour.Behaviour):
    """배터리 ≤ 15% 시 ``battery_low`` FSM trigger 발화 (hysteresis 25% 진출)."""

    LOW_ENTER = 15.0  # 진입 임계 (%)
    LOW_EXIT = 25.0   # 진출 임계 (%) — chattering 방지

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context
        self.bb = self.attach_blackboard_client(name=name)
        self.bb.register_key(key=Keys.BATTERY_LEVEL, access=Access.READ)
        self._fired = False
        # 시연/디버그 환경 — disable_battery_safety:=true 면 battery_low trigger 발화 skip.
        self._disabled = is_safety_disabled(
            getattr(self.ctx, "node", None), "battery", monitor_name=self.name,
        )

    def initialise(self) -> None:
        # 트리 swap 시 (re-entry) 다시 발화 가능하게.
        self._fired = False

    def update(self) -> Status:
        if self._disabled:
            return Status.RUNNING
        try:
            level = float(self.bb.get(Keys.BATTERY_LEVEL))
        except (KeyError, TypeError, ValueError):
            return Status.RUNNING

        if self._fired:
            # hysteresis — 55% 위로 회복되면 reset (다시 떨어지면 재발화 가능)
            if level >= self.LOW_EXIT:
                self._fired = False
        else:
            if level <= self.LOW_ENTER:
                self._fired = True
                self.ctx.fsm.trigger("battery_low")

        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        # idempotent — 별도 cleanup 없음
        pass
