"""VerifyDockingContact — ReverseIntoDock 완료 후 ``docked`` trigger 발사.

ReturnSubTree 의 4단계 (마지막). 자동 도킹 접점 센서는 미구현이라 시간 기반 후진이
끝났으면 도크 도달 간주하고 ``fsm.trigger("docked")`` 발사 → RETURNING /
LOW_BATTERY_RETURN → CHARGING 자동 전이.

Status:
  SUCCESS — trigger 발사 후 (매 tick 즉시 SUCCESS, 단 trigger 는 1회만)

terminate(INVALID): cleanup 없음 (단순 trigger 발사).

추후 접점 센서 통합 시: ``blackboard.DOCKING_CONTACT`` 가 True 일 때만 발사 +
False 면 FAILURE 로 ReverseIntoDock 재시도 등.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Status

if TYPE_CHECKING:
    from ....context import Context


class VerifyDockingContact(py_trees.behaviour.Behaviour):
    """1 tick 안에 ``docked`` trigger 발사 후 SUCCESS — Sequence 의 마지막 자식."""

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context
        self._fired = False

    def initialise(self) -> None:
        self._fired = False

    def update(self) -> Status:
        if not self._fired:
            try:
                self.ctx.fsm.trigger("docked")
            except Exception:
                # transitions 라이브러리: 현재 state 에서 invalid trigger 면 무시 (idempotent)
                pass
            self._fired = True
        return Status.SUCCESS

    def terminate(self, new_status: Status) -> None:
        pass
