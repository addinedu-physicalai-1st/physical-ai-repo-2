"""AwaitRecruitComplete — control-service 가 blackboard.HIDESEEK_REGISTERED_IDS 를
세팅할 때까지 RUNNING, 세팅되면 SUCCESS.

UI 의 recruit phase 종료 ("출발" 버튼) →
  POST /api/gogoping/play/hideseek/recruit-complete {child_ids: [...]}
  → ros_bridge 가 blackboard.HIDESEEK_REGISTERED_IDS = child_ids 세팅
  → 본 behaviour SUCCESS → Sequence 다음 (Countdown).

reconciler 가 HIDEANDSEEK 진입 시마다 본 키를 [] 로 reset 하므로,
"다시 하기" 같은 재진입에서도 처음엔 RUNNING 으로 시작.
"""
from __future__ import annotations

import py_trees
from py_trees.common import Access

from ...blackboard import Keys


class AwaitRecruitComplete(py_trees.behaviour.Behaviour):
    """blackboard.HIDESEEK_REGISTERED_IDS 비어있지 않으면 SUCCESS, 비어있으면 RUNNING."""

    def __init__(self, name: str) -> None:
        super().__init__(name=name)
        self.bb = self.attach_blackboard_client(name=self.name)
        self.bb.register_key(key=Keys.HIDESEEK_REGISTERED_IDS, access=Access.READ)

    def update(self) -> py_trees.common.Status:
        try:
            ids = self.bb.get(Keys.HIDESEEK_REGISTERED_IDS)
        except KeyError:
            return py_trees.common.Status.RUNNING
        if ids:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.RUNNING
