"""SetDestinationKey — blackboard.DESTINATION_KEY = key, 즉시 SUCCESS.

`build_goto_subtree(ctx)` 가 인자를 안 받고 `Keys.DESTINATION_KEY` 만 읽으므로,
hideseek sub 처럼 한 sequence 안에서 goto 를 여러 번 (또는 GOTO state 외에서)
호출하려면 매 진입 시 destination 을 미리 셋팅해야 한다.

블랙보드 키 자체는 GOTO state 의 reconciler 가 이미 다른 흐름에서 W (state 동시
진입 불가라 충돌 없음). 본 behaviour 는 _그 키를 다른 state 안에서도 셋_ 하기
위한 helper.
"""
from __future__ import annotations

import py_trees
from py_trees.common import Access

from ...blackboard import Keys


class SetDestinationKey(py_trees.behaviour.Behaviour):
    """blackboard.DESTINATION_KEY = key, 즉시 SUCCESS."""

    def __init__(self, name: str, key: str) -> None:
        super().__init__(name=name)
        self._key = key
        self.bb = self.attach_blackboard_client(name=self.name)
        self.bb.register_key(key=Keys.DESTINATION_KEY, access=Access.WRITE)

    def update(self) -> py_trees.common.Status:
        self.bb.set(Keys.DESTINATION_KEY, self._key)
        return py_trees.common.Status.SUCCESS
