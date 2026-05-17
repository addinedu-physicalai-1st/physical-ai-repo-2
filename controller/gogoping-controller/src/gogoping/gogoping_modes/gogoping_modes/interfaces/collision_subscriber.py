"""Nav2 Collision Monitor 상태 구독 → blackboard.collision_state 갱신 (TODO).

# STUB
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import rclpy.node


class CollisionSubscriber:
    """추후 nav2 collision_monitor 상태 토픽 구독으로 구현.

    수신 시 ``blackboard.COLLISION_STATE`` 을 "ok" / "warn" / "fault" 로 W.
    """

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
