"""gogoping_camera_pan 토픽 publish 래퍼 (Day 2 TODO).

# STUB: replace Day 2
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import rclpy.node


class CameraPanClient:
    """Day 2 에 /camera_pan/auto publish 로 구현.

    예상 API: set_target(yaw_rad, pitch_rad), sweep(start, end, period), set_idle().
    """

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
