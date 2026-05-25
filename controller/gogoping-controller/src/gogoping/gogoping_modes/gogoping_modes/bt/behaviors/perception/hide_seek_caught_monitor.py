"""HideSeekCaughtMonitor — registered_ids ⊆ caught_ids 이면 SUCCESS.

BT_hide_and_seek_sub 의 patrol / return parallel 안에서 작동.
SUCCESS → 부모 parallel 의 SuccessOnOne 정책에 의해 parallel SUCCESS →
Sequence 다음 step.

registered_ids 가 비어있으면 RUNNING — 모집 전 잘못된 노드 진입 시 의미
없는 즉시 SUCCESS 방지 (정상 흐름에선 AwaitRecruitComplete 가 먼저
RUNNING → registered_ids 셋 되면 SUCCESS → 그 다음 patrol 진입).
"""
from __future__ import annotations

import py_trees
from py_trees.common import Access

from ...blackboard import Keys


class HideSeekCaughtMonitor(py_trees.behaviour.Behaviour):
    """잡힌 child_id 가 등록자 전체를 포함하면 SUCCESS."""

    def __init__(self, name: str) -> None:
        super().__init__(name=name)
        self.bb = self.attach_blackboard_client(name=self.name)
        self.bb.register_key(key=Keys.HIDESEEK_REGISTERED_IDS, access=Access.READ)
        self.bb.register_key(key=Keys.HIDESEEK_CAUGHT_IDS, access=Access.READ)

    def update(self) -> py_trees.common.Status:
        try:
            registered = self.bb.get(Keys.HIDESEEK_REGISTERED_IDS) or []
            caught = self.bb.get(Keys.HIDESEEK_CAUGHT_IDS) or []
        except KeyError:
            return py_trees.common.Status.RUNNING
        if not registered:
            return py_trees.common.Status.RUNNING
        if set(registered).issubset(set(caught)):
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.RUNNING
