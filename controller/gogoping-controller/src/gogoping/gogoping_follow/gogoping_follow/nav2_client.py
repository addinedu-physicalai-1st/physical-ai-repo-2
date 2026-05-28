"""Nav2 NavigateToPose 액션 client wrapper.

목표:
- send_goal(pose): 비동기 send. 이전 goal handle 가 살아 있으면 cancel 후 새로.
- cancel_current(): 현재 goal cancel.
- last_status: "idle" | "active" | "succeeded" | "aborted" | "canceled".
"""
from __future__ import annotations

from typing import Optional

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import Pose, PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node

from gogoping_follow.config import MAP_FRAME


class Nav2Client:
    def __init__(self, node: Node) -> None:
        self._node = node
        self._client = ActionClient(node, NavigateToPose, "/navigate_to_pose")
        self._goal_handle = None
        self._status: str = "idle"

    @property
    def status(self) -> str:
        return self._status

    def server_ready(self, timeout_s: float = 0.1) -> bool:
        return self._client.wait_for_server(timeout_sec=timeout_s)

    def send_goal(self, pose: Pose, behavior_tree: str = "") -> None:
        """NavigateToPose 액션 호출. behavior_tree="" 면 Nav2 default 사용.

        추종 모드는 follow_person_bt.xml (FollowPersonPath controller) 사용해
        잔진동 ↓. 다른 흐름 (vertex 이동, 도킹) 은 default BT 유지.
        """
        if not self.server_ready():
            self._node.get_logger().warn("Nav2 액션 서버 미준비 — goal skip")
            return

        # 이전 goal 이 살아 있으면 cancel 후 새로.
        self.cancel_current()

        goal_msg = NavigateToPose.Goal()
        ps = PoseStamped()
        ps.header.frame_id = MAP_FRAME
        ps.header.stamp = self._node.get_clock().now().to_msg()
        ps.pose = pose
        goal_msg.pose = ps
        goal_msg.behavior_tree = behavior_tree

        send_future = self._client.send_goal_async(goal_msg)
        send_future.add_done_callback(self._on_goal_response)
        self._status = "active"

    def cancel_current(self) -> None:
        if self._goal_handle is None:
            return
        try:
            self._goal_handle.cancel_goal_async()
        except Exception as e:  # noqa: BLE001
            self._node.get_logger().debug(f"goal cancel exception: {e}")
        self._goal_handle = None

    def _on_goal_response(self, future) -> None:
        try:
            handle = future.result()
        except Exception as e:  # noqa: BLE001
            self._node.get_logger().warn(f"send_goal future error: {e}")
            self._status = "aborted"
            return
        if not handle.accepted:
            self._node.get_logger().info("Nav2 goal rejected")
            self._status = "aborted"
            return
        self._goal_handle = handle
        result_future = handle.get_result_async()
        result_future.add_done_callback(self._on_result)

    def _on_result(self, future) -> None:
        try:
            wrapped = future.result()
        except Exception as e:  # noqa: BLE001
            self._node.get_logger().debug(f"goal result error: {e}")
            self._status = "aborted"
            return
        status = wrapped.status
        if status == GoalStatus.STATUS_SUCCEEDED:
            self._status = "succeeded"
        elif status == GoalStatus.STATUS_CANCELED:
            self._status = "canceled"
        else:
            self._status = "aborted"
