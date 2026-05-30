"""SetPatrolIndex — 1-tick BB write + SUCCESS.

``BT_patrol_sub`` 의 각 ``visit_<name>`` Sequence 첫 자식으로 삽입. visit 시작 시점에
``blackboard.PATROL_CURRENT_INDEX`` 를 vertex 인덱스로 갱신 → admin UI 가
state snapshot 통해 받아 시각화 (번호 / X / 강조).

값 의미 (``Keys.PATROL_CURRENT_INDEX``):
- ``-1``: idle (patrol 미진행)
- ``i in [0, N)``: i 번째 vertex 의 visit 진행 중 (nav/brake/sweep 중 하나)
- ``N``: 모든 vertex 완료

| 파일 | bt/behaviors/common/set_patrol_index.py |
| Used in | BT_patrol_sub (visit_<name> Sequence 의 첫 자식 + 끝 마무리) |
"""
from __future__ import annotations

import py_trees
from py_trees.common import Access, Status

from ...blackboard import Keys


class SetPatrolIndex(py_trees.behaviour.Behaviour):
    """visit 시작/종료 시 blackboard.PATROL_CURRENT_INDEX 를 ``index`` 로 W 후 SUCCESS."""

    def __init__(self, name: str, index: int):
        super().__init__(name)
        self._index = int(index)
        self.bb = self.attach_blackboard_client(name=name)
        self.bb.register_key(key=Keys.PATROL_CURRENT_INDEX, access=Access.WRITE)

    def update(self) -> Status:
        self.bb.set(Keys.PATROL_CURRENT_INDEX, self._index)
        return Status.SUCCESS
