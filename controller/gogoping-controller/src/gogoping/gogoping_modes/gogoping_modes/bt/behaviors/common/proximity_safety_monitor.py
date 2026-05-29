"""ProximitySafetyMonitor — 사람 근접 상태 관측 leaf (person-only).

## 책임 (관측·표시 전용 — 반응 X)

perception 이 발행하는 ``/gogoping/proximity_event`` (JSON: level / person_dist_m /
wall_dist_m) 를 구독해 현재 근접 level 을 blackboard(``PROXIMITY_LEVEL``)에 기록한다.
admin UI 트리에서 본 leaf 의 존재·status·disabled 로 proximity safety 활성 여부를
한눈에 확인 가능.

**실제 정지·60s 유지·reroute·후진 반응은 graph_router (`_act_navigate_impl`) 가 수행**한다.
본 leaf 는 그 반응을 BT main leaf 로 "표현"하고 토글 상태를 노출하는 역할만 한다
(사용자 요청: battery/error 처럼 켜고 끌 수 있는 main leaf 로 표현 — 얇은 버전).

## 토글

``NO_PROXIMITY_SAFETY=1`` → device 스크립트가 modes 노드에 ``disable_proximity_safety:=true``
+ graph_router 에도 동일 param 전달. 본 leaf 는 modes 측 param 을 ``is_safety_disabled(
node, "proximity")`` 로 읽어 ``self._disabled`` 저장 → tree_inspector 가 admin UI 에
dim/strikethrough 로 표시. (기능 gating 은 graph_router 가 담당하므로 leaf 가 disabled
여도 동작 자체는 동일 — 단지 표시.)

## monitor 컨벤션 (docs/conventions.md §2)

- ``setup()``: ``/gogoping/proximity_event`` 구독 1회 생성 (CommandListener 와 동일 — ROS
  리소스는 setup 에서).
- ``update()``: 매 tick ``PROXIMITY_LEVEL`` blackboard W 후 RUNNING 리턴. SUCCESS/FAILURE 금지.
- edge-trigger / FSM trigger 발화 없음 — 관측 전용 (battery/map_boundary 와 다른 점).
"""
from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

import py_trees
from py_trees.common import Access, Status

from ...blackboard import Keys
from ....utils.safety_flags import is_safety_disabled

if TYPE_CHECKING:
    from ....context import Context


_TOPIC = "/gogoping/proximity_event"


class ProximitySafetyMonitor(py_trees.behaviour.Behaviour):
    """``/gogoping/proximity_event`` 구독 → ``blackboard.PROXIMITY_LEVEL`` W (관측 전용)."""

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context
        self.bb = self.attach_blackboard_client(name=name)
        self.bb.register_key(key=Keys.PROXIMITY_LEVEL, access=Access.WRITE)
        self._level: str = "ok"
        self._sub: Any = None
        # 시연/디버그 — disable_proximity_safety:=true 면 admin UI 에 disabled 표시.
        # 실제 반응 gating 은 graph_router 가 동일 param 으로 수행.
        self._disabled = is_safety_disabled(
            getattr(self.ctx, "node", None), "proximity", monitor_name=self.name,
        )

    def setup(self, **kwargs: Any) -> None:
        """트리 setup 시 — proximity_event 구독 생성. 트리 swap 마다 leaf 가 재생성되므로
        이전 인스턴스가 terminate 에서 구독을 정리하고 새 인스턴스가 여기서 다시 생성한다
        (구독 누수 방지). 이미 있으면 skip (idempotent)."""
        if self._sub is not None:
            return
        node = getattr(self.ctx, "node", None)
        if node is None:
            return
        from std_msgs.msg import String
        self._sub = node.create_subscription(
            String, _TOPIC, self._on_proximity_event, 10,
        )

    def _on_proximity_event(self, msg: Any) -> None:
        try:
            payload = json.loads(msg.data)
        except (json.JSONDecodeError, AttributeError, TypeError):
            return
        self._level = str(payload.get("level", "ok"))

    def update(self) -> Status:
        # 관측 전용 — 현재 level 을 blackboard 에 노출, 항상 RUNNING.
        self.bb.set(Keys.PROXIMITY_LEVEL, self._level)
        self.feedback_message = (
            f"level={self._level}" + (" (disabled)" if self._disabled else "")
        )
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        # 트리 swap(teardown) 시 INVALID 로 호출 — 구독 정리해 누수 방지.
        # (always-RUNNING monitor 라 terminate 는 트리 stop 시에만 호출됨)
        if self._sub is not None:
            node = getattr(self.ctx, "node", None)
            if node is not None:
                try:
                    node.destroy_subscription(self._sub)
                except Exception:
                    pass
            self._sub = None
