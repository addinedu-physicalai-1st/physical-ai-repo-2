"""SetHideseekPhase — blackboard.HIDESEEK_PHASE 에 phase 문자열 셋 후 SUCCESS.

BT_hide_and_seek_sub Sequence 의 각 step 진입 직전에 끼워 넣어
UI 에게 현재 단계 알림. snapshot 의 `hideseek_phase` 필드로 흘러나감.

phase 값:
  "move_to_play" / "recruit" / "countdown" / "patrol" / "return" / "end"
  "" — 비활성 (HIDEANDSEEK 아닐 때)

진입 시 1회만 발화하면 충분하지만, parallel 안에서 다른 자식이 RUNNING 인
동안 본 behaviour 가 다시 tick 되어도 같은 값 재셋팅이라 무해.
"""
from __future__ import annotations

import py_trees
from py_trees.common import Access

from ...blackboard import Keys


class SetHideseekPhase(py_trees.behaviour.Behaviour):
    """blackboard.HIDESEEK_PHASE = phase, 즉시 SUCCESS."""

    def __init__(self, name: str, phase: str) -> None:
        super().__init__(name=name)
        self._phase = phase
        self.bb = self.attach_blackboard_client(name=self.name)
        self.bb.register_key(key=Keys.HIDESEEK_PHASE, access=Access.WRITE)

    def update(self) -> py_trees.common.Status:
        self.bb.set(Keys.HIDESEEK_PHASE, self._phase)
        return py_trees.common.Status.SUCCESS
