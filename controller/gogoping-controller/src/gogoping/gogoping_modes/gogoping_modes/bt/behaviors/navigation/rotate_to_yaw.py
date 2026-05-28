"""RotateToYaw — 현재 위치에서 yaw 만 target 값으로 회전 (nav2 NavigateToPose 사용).

blackboard.ROBOT_POSE 의 (x, y) 를 그대로, yaw 만 인자로 받아 NavigateToPose
goal 을 발사. nav2 의 controller + goal_checker (yaw_goal_tolerance) 가
회전 완료 시점 결정 → 도착 시 SUCCESS.

| 파일 | bt/behaviors/navigation/rotate_to_yaw.py |
| Used in | BT_hide_and_seek_sub (step_move_to_play 끝 / step_recruit 끝) |
"""
from __future__ import annotations

import math
from typing import Any

import py_trees
from py_trees.common import Access
from rclpy.action import ActionClient

from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose

from ...blackboard import Keys


class RotateToYaw(py_trees.behaviour.Behaviour):
    DEFAULT_ACTION = "/navigate_to_pose"
    DEFAULT_FRAME_ID = "map"

    def __init__(
        self,
        name: str,
        target_yaw: float,
        action_name: str = DEFAULT_ACTION,
        frame_id: str = DEFAULT_FRAME_ID,
    ) -> None:
        super().__init__(name)
        self._target_yaw = float(target_yaw)
        self._action_name = action_name
        self._frame_id = frame_id
        self._client: ActionClient | None = None
        self._node: Any = None
        self._goal_handle = None
        self._cancel_pending: bool = False
        self._result_status: str | None = None
        self._failure_reason: str = ""
        self._debug_events: Any = None
        self.blackboard = self.attach_blackboard_client(name=self.qualified_name)
        self.blackboard.register_key(key=Keys.ROBOT_POSE, access=Access.READ)

    def setup(self, **kwargs: Any) -> None:
        try:
            self._node = kwargs["node"]
        except KeyError as e:
            raise KeyError("setup() requires 'node' kwarg (rclpy node)") from e
        self._client = ActionClient(self._node, NavigateToPose, self._action_name)
        self._debug_events = kwargs.get("debug_events")

    def _dbg(self, msg: str, level: str = "info") -> None:
        if self._debug_events is not None:
            try:
                self._debug_events.event("RotateToYaw", msg, level=level)
            except Exception:
                pass

    def _make_goal(self, x: float, y: float, yaw: float) -> NavigateToPose.Goal:
        goal = NavigateToPose.Goal()
        ps = PoseStamped()
        ps.header.frame_id = self._frame_id
        ps.header.stamp = self._node.get_clock().now().to_msg()
        ps.pose.position.x = float(x)
        ps.pose.position.y = float(y)
        ps.pose.orientation.z = float(math.sin(yaw / 2.0))
        ps.pose.orientation.w = float(math.cos(yaw / 2.0))
        goal.pose = ps
        return goal

    def initialise(self) -> None:
        self._goal_handle = None
        self._cancel_pending = False
        self._result_status = None
        self._failure_reason = ""
        try:
            pose = self.blackboard.get(Keys.ROBOT_POSE)
        except KeyError:
            self._result_status = "failed"
            self._failure_reason = "blackboard.ROBOT_POSE not set"
            return
        if not isinstance(pose, dict) or "x" not in pose or "y" not in pose:
            self._result_status = "failed"
            self._failure_reason = f"invalid pose: {pose!r}"
            return
        if self._client is None or not self._client.server_is_ready():
            if self._client is None or not self._client.wait_for_server(timeout_sec=0.5):
                self._result_status = "failed"
                self._failure_reason = "nav2 action server unavailable"
                return
        goal = self._make_goal(pose["x"], pose["y"], self._target_yaw)
        send_future = self._client.send_goal_async(goal)
        send_future.add_done_callback(self._on_goal_response)
        self._dbg(
            f"send → ({pose['x']:.2f}, {pose['y']:.2f}, yaw={self._target_yaw:.3f})"
        )

    def _on_goal_response(self, fut: Any) -> None:
        gh = fut.result()
        if not gh.accepted:
            self._result_status = "failed"
            self._failure_reason = "rejected"
            self._dbg("gh rejected", level="warn")
            return
        self._goal_handle = gh
        if self._cancel_pending:
            try:
                gh.cancel_goal_async()
            except Exception:
                pass
            self._cancel_pending = False
            self._dbg("race cancel via pending flag", level="warn")
            return
        result_fut = gh.get_result_async()
        result_fut.add_done_callback(self._on_result)

    def _on_result(self, fut: Any) -> None:
        wrapper = fut.result()
        # NavigateToPose 의 result 는 비어있음 — 성공/실패는 status code 로 판정
        status = wrapper.status
        from action_msgs.msg import GoalStatus
        if status == GoalStatus.STATUS_SUCCEEDED:
            self._result_status = "succeeded"
            self._dbg(f"SUCCESS yaw={self._target_yaw:.3f}")
        else:
            self._result_status = "failed"
            self._failure_reason = f"nav2 status={status}"
            self._dbg(f"FAILURE status={status}", level="warn")

    def update(self) -> py_trees.common.Status:
        if self._result_status == "succeeded":
            return py_trees.common.Status.SUCCESS
        if self._result_status == "failed":
            self.feedback_message = self._failure_reason
            return py_trees.common.Status.FAILURE
        return py_trees.common.Status.RUNNING

    def terminate(self, new_status: py_trees.common.Status) -> None:
        if new_status != py_trees.common.Status.INVALID:
            return
        if self._goal_handle is not None:
            try:
                self._goal_handle.cancel_goal_async()
            except Exception:
                pass
            self._goal_handle = None
            self._dbg("terminate(INVALID) gh=present → cancel")
        else:
            self._cancel_pending = True
            self._dbg("terminate(INVALID) gh=None → pending", level="warn")
