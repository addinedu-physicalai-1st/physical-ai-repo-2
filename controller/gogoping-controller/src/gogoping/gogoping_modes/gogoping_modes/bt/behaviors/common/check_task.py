"""CheckTask — TaskSelector 분기용 Condition.

blackboard 의 ``ASSIST_TASK`` 또는 ``PLAY_TASK`` 값을 expected 와 비교.

사용 예 (``BT_assist_main``):
    Selector("TaskSelector", memory=False, children=[
        Sequence(children=[CheckTask(Keys.ASSIST_TASK, "carry"), CarrySubTree]),
        Sequence(children=[CheckTask(Keys.ASSIST_TASK, "follow"), FollowSubTree]),
        Sequence(children=[CheckTask(Keys.ASSIST_TASK, "lullaby"), LullabySubTree]),
    ])
"""
from __future__ import annotations

import py_trees
from py_trees.common import Access, Status


class CheckTask(py_trees.behaviour.Behaviour):
    """blackboard 의 key 값이 ``expected`` 와 일치하면 SUCCESS, 아니면 FAILURE.

    Condition 이므로 RUNNING 안 함 — 항상 즉시 SUCCESS / FAILURE.
    """

    def __init__(self, key: str, expected: str, name: str | None = None):
        # 이름이 없으면 자동으로 가독성 좋게 — "CheckTask(assist_task=='carry')"
        super().__init__(name or f"CheckTask({key}=={expected!r})")
        self._key = key
        self._expected = expected
        self.bb = self.attach_blackboard_client(name=self.name)
        self.bb.register_key(key=key, access=Access.READ)

    def update(self) -> Status:
        try:
            value = self.bb.get(self._key)
        except KeyError:
            # blackboard 에 키가 미등록 — init_blackboard() 안 했거나 다른 layer 버그
            return Status.FAILURE
        return Status.SUCCESS if value == self._expected else Status.FAILURE
