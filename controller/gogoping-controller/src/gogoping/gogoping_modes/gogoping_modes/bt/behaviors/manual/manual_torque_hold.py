"""ManualTorqueHold — MANUAL state 진입 시 motor torque OFF, 나갈 때 ON 복원.

MANUAL state 의 의도: 사용자가 로봇을 **직접 손으로 밀어** 위치 조정. motor 가 토크
유지하면 못 밈 → ``initialise()`` 에서 base_driver.release_torque() 호출.
다른 state 로 전이하면 ``terminate(new_status)`` 가 호출돼서 enable_torque() 복원
(``main.py:_build_tree_for_state`` 가 명시적 ``tree.shutdown()`` 호출 → 자식
terminate 전파).

``BT_manual_main`` 에만 배치. py_trees Parallel 의 자식.

monitor 컨벤션 (``docs/conventions.md`` §2):
- 매 tick RUNNING 리턴 (SUCCESS / FAILURE 금지 — Parallel 부모를 떨어뜨림)
- ``initialise()`` 가 release_torque() 호출 → idempotent (driver 가 같은 상태 재호출 OK)
- ``terminate()`` 가 enable_torque() 호출 → idempotent. 안전 우선이라 항상 호출 (재진입 보호용)
- blackboard ``MANUAL_TORQUE_ACTIVE`` (bool) write — admin UI 가 표시 가능
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Access, Status

from ...blackboard import Keys

if TYPE_CHECKING:
    from ....context import Context


class ManualTorqueHold(py_trees.behaviour.Behaviour):
    """initialise 에서 torque OFF, terminate 에서 torque ON 복원."""

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context
        self.bb = self.attach_blackboard_client(name=name)
        self.bb.register_key(key=Keys.MANUAL_TORQUE_ACTIVE, access=Access.WRITE)

    def initialise(self) -> None:
        """MANUAL 진입 — torque OFF (motor free-wheel)."""
        ok = self._release()
        # blackboard 는 release 성공 여부와 무관하게 의도 반영 — UI 표시는 "사용자 의도"
        self.bb.set(Keys.MANUAL_TORQUE_ACTIVE, True)
        if not ok:
            # 실패 시도 — RUNNING 유지하되 로그로 알림 (다음 tick 에서 재시도는 안 함)
            self.logger.warning(
                "ManualTorqueHold: release_torque 실패 — 모터가 여전히 토크 유지 중일 수 있음"
            )

    def update(self) -> Status:
        # monitor 컨벤션 — 항상 RUNNING. 매 tick 추가 작업 없음.
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        """MANUAL 나감 — torque ON 복원. idempotent."""
        # 디버그 — terminate 가 실제로 호출되는지 추적
        self.logger.info(f"ManualTorqueHold.terminate(new_status={new_status}) — calling enable_torque")
        ok = self._enable()
        self.bb.set(Keys.MANUAL_TORQUE_ACTIVE, False)
        if not ok:
            self.logger.warning(
                "ManualTorqueHold: enable_torque 실패 — 모터가 disable 상태일 수 있음 (수동 enable 필요)"
            )

    # --------------------------------------------------------------- helpers

    def _release(self) -> bool:
        driver = getattr(self.ctx, "base_driver", None)
        if driver is None:
            self.logger.warning("ManualTorqueHold: ctx.base_driver 없음 — skip")
            return False
        return driver.release_torque()

    def _enable(self) -> bool:
        driver = getattr(self.ctx, "base_driver", None)
        if driver is None:
            return False
        return driver.enable_torque()
