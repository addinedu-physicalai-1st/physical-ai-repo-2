"""Nav2 Collision Monitor 상태 구독 → blackboard.COLLISION_STATE 갱신.

데이터 plane 의 nav2 ``collision_monitor`` 노드가 LiDAR stop zone 으로 cmd_vel 을 끊으면
``nav2_msgs/CollisionMonitorState`` (``~/collision_monitor_state``) 로 현재 action 을 발행.
본 구독자가 그 ``action_type`` 을 ``"ok"`` / ``"stop"`` 으로 매핑해 blackboard 에 W.

BT 의 ``CollisionMonitor`` leaf 가 이 값을 읽어 stop 5분 지속 시 cancel/fault 발화.
실제 정지(cmd_vel zero)는 collision_monitor 노드가 담당 — 본 구독자는 관측/반응용.

stop-only 설정이지만 방어적으로 nonzero action(slowdown/approach 등)도 "stop" 취급.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Access

from ..bt.blackboard import Keys

if TYPE_CHECKING:
    import rclpy.node


def collision_state_from_action(action_type: int) -> str:
    """``CollisionMonitorState.action_type`` → ``"ok"`` | ``"stop"`` (pure).

    DO_NOTHING(0) → "ok", 그 외(STOP/SLOWDOWN/APPROACH/LIMIT) → "stop".
    """
    return "ok" if int(action_type) == 0 else "stop"


class CollisionSubscriber:
    """``/collision_monitor_state`` 구독 → blackboard.COLLISION_STATE W."""

    TOPIC = "/collision_monitor_state"   # 절대경로 — root namespace 의 collision_monitor
    QOS_DEPTH = 10

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
        self._bb = py_trees.blackboard.Client(name="CollisionSubscriber")
        self._bb.register_key(key=Keys.COLLISION_STATE, access=Access.WRITE)

        from nav2_msgs.msg import CollisionMonitorState
        self._sub = node.create_subscription(
            CollisionMonitorState, self.TOPIC, self._on_state, self.QOS_DEPTH,
        )

    def _on_state(self, msg) -> None:
        self._bb.set(Keys.COLLISION_STATE, collision_state_from_action(msg.action_type))
