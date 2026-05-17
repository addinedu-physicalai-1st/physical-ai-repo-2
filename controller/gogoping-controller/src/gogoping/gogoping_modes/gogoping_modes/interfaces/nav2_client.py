"""Nav2 NavigateToPose 액션 클라이언트 (Day 2 TODO).

# STUB: replace Day 2
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import rclpy.node


class Nav2Client:
    """Day 2 에 nav2_msgs/action/NavigateToPose 클라이언트로 구현.

    예상 API: send_goal(pose_name) -> goal_handle, poll_status(handle) -> Status, cancel(handle).
    """

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
