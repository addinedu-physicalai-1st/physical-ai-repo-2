"""MapBoundaryMonitor — 로봇 pose 가 맵 영역 밖이면 ``fault`` 발화.

판별 알고리즘 (``docs/bt/behaviors/common.md#map_boundary_monitor``):
- ``ctx.map_cache.is_outside(x, y)`` — OccupancyGrid 기반:
    1. 격자 박스 (width × height) 밖 → 맵 밖
    2. 박스 안이지만 ``data[idx] == -1`` (unknown 셀) → 맵 밖
       (SLAM 으로 만든 비정형 맵 — L자 / ㄷ자 등 자동 처리)
- 맵 미수신 시 (``is_outside`` 가 ``None`` 리턴) → 발화 안 함 (보수적 default)

배치:
- ``BT_assist_main``, ``BT_play_main``, ``BT_returning_main`` (자동 ERROR 전이 가능 state)
- ``MANUAL`` 의도적 제외 — 사용자가 직접 들고 가도 ERROR 안 됨 (``docs/state-bt.md``)

monitor 컨벤션 (``docs/conventions.md`` §2):
- 매 tick RUNNING 리턴
- edge-triggered — 1회 발화 후 ``ERROR`` terminal 이라 re-arm 불필요. ``initialise()`` 가
  새 트리 진입 시 호출하므로 ASSIST/PLAY/RETURNING 재진입 시 다시 발화 가능.
- 발화 전 ``blackboard.ERROR_REASON / ERROR_SOURCE`` 세팅 (admin UI 가 빨간 알약 옆에 표시 가능).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Access, Status

from ...blackboard import Keys

if TYPE_CHECKING:
    from ....context import Context


_REASON = "out_of_map"


class MapBoundaryMonitor(py_trees.behaviour.Behaviour):
    """blackboard.ROBOT_POSE 가 맵 밖이면 ``fault(reason="out_of_map")`` 발화."""

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context
        self.bb = self.attach_blackboard_client(name=name)
        self.bb.register_key(key=Keys.ROBOT_POSE, access=Access.READ)
        self.bb.register_key(key=Keys.ERROR_REASON, access=Access.WRITE)
        self.bb.register_key(key=Keys.ERROR_SOURCE, access=Access.WRITE)
        self._fired = False

    def initialise(self) -> None:
        # 트리 swap 시 (ASSIST/PLAY/RETURNING 재진입) 다시 발화 가능하게.
        self._fired = False

    def update(self) -> Status:
        if self._fired:
            return Status.RUNNING

        try:
            pose = self.bb.get(Keys.ROBOT_POSE)
            x = float(pose["x"])
            y = float(pose["y"])
        except (KeyError, TypeError, ValueError):
            return Status.RUNNING

        outside = self.ctx.map_cache.is_outside(x, y)
        if outside is True:
            # 1) blackboard 에 사유 기록 (admin UI 가 ERROR 알약 옆에 표시 가능)
            self.bb.set(Keys.ERROR_REASON, _REASON)
            self.bb.set(Keys.ERROR_SOURCE, self.name)
            # 2) FSM 강제 ERROR 전이
            self.ctx.fsm.trigger("fault", reason=_REASON)
            self._fired = True

        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        # idempotent — 별도 cleanup 없음
        pass
