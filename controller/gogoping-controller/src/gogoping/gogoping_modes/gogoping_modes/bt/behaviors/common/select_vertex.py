"""SelectVertex — 고정된 vertex 이름을 blackboard.target_vertex_name 에 W 후 SUCCESS.

NavigateToVertex behaviour 가 ``target_vertex_name`` key 를 R 하므로, 서브트리 빌드 시
vertex 마다 ``SelectVertex(vertex_name=name) → NavigateToVertex`` Sequence 를 생성하면
N 개 vertex 동적 순회 가능.

사용 예 (BT_patrol_sub):
    Sequence("visit_A", memory=True, children=[
        SelectVertex("select_A", vertex_name="A"),
        NavigateToVertex("nav_A"),
        PanCameraSweep("sweep_A", ctx),
    ])

Condition 이 아니라 *action* 이므로 RUNNING 안 함 — 즉시 SUCCESS.
"""
from __future__ import annotations

import py_trees
from py_trees.common import Access, Status


# NavigateToVertex.DEFAULT_TARGET_KEY 와 일치하는 string literal.
# 향후 Keys 에 등재 시 blackboard.py / blackboard-schema.md 같이 갱신.
TARGET_VERTEX_KEY = "target_vertex_name"


class SelectVertex(py_trees.behaviour.Behaviour):
    """고정된 vertex 이름을 blackboard 에 W 하는 1-tick behaviour."""

    def __init__(
        self,
        name: str,
        vertex_name: str,
        target_key: str = TARGET_VERTEX_KEY,
    ) -> None:
        super().__init__(name)
        self._vertex_name = str(vertex_name)
        self._target_key = target_key
        self.bb = self.attach_blackboard_client(name=self.name)
        self.bb.register_key(key=self._target_key, access=Access.WRITE)

    def update(self) -> Status:
        self.bb.set(self._target_key, self._vertex_name)
        return Status.SUCCESS
