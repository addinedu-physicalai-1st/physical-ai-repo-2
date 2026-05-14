"""Graph Router ROS 노드.

- waypoints.yaml + lanes.yaml 로드 (ament_index 의 share/gogoping_navigation/config)
- /odom 구독 → 현재 로봇 위치 추적
- service /graph_router/route (RouteToVertex) — 시각화/디버깅용
- action  /graph_router/navigate_to_vertex (NavigateToVertex)
   → 다익스트라로 vertex sequence 계산
   → nav2 의 /follow_waypoints (FollowWaypoints) 액션 클라이언트로 위임
   → feedback 중계
"""
from __future__ import annotations

import math
from pathlib import Path
from threading import Lock

import rclpy
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import FollowWaypoints
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient, ActionServer
from rclpy.action.server import ServerGoalHandle
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from gogoping_msgs.action import NavigateToVertex
from gogoping_msgs.srv import RouteToVertex
from gogoping_navigation.graph import Graph


class GraphRouterNode(Node):
    def __init__(self) -> None:
        super().__init__("graph_router_node")
        share = Path(get_package_share_directory("gogoping_navigation"))
        wp_path = Path(self.declare_parameter(
            "waypoints_yaml", str(share / "config" / "waypoints.yaml")
        ).value)
        lanes_path = Path(self.declare_parameter(
            "lanes_yaml", str(share / "config" / "lanes.yaml")
        ).value)
        self._frame_id = self.declare_parameter("frame_id", "map").value
        self._odom_topic = self.declare_parameter("odom_topic", "/odom").value
        self._follow_action = self.declare_parameter(
            "follow_action", "/follow_waypoints"
        ).value

        self._graph = Graph.from_yaml(wp_path, lanes_path=lanes_path)
        self.get_logger().info(
            f"graph: {len(self._graph.vertices)} vertex, "
            f"{len(self._graph.lanes())} lane"
        )

        self._pose_lock = Lock()
        self._cur_xy: tuple[float, float] | None = None

        cb = ReentrantCallbackGroup()
        self.create_subscription(
            Odometry, self._odom_topic, self._on_odom, 10, callback_group=cb,
        )
        self.create_service(
            RouteToVertex, "/graph_router/route", self._srv_route,
            callback_group=cb,
        )
        self._nav_ac: ActionClient = ActionClient(
            self, FollowWaypoints, self._follow_action, callback_group=cb,
        )
        self._action_server = ActionServer(
            self,
            NavigateToVertex,
            "/graph_router/navigate_to_vertex",
            execute_callback=self._act_navigate,
            callback_group=cb,
        )

    # ──────── /odom ────────
    def _on_odom(self, msg: Odometry) -> None:
        with self._pose_lock:
            self._cur_xy = (
                msg.pose.pose.position.x,
                msg.pose.pose.position.y,
            )

    def _current_xy(self) -> tuple[float, float] | None:
        with self._pose_lock:
            return self._cur_xy

    # ──────── service: route ────────
    def _srv_route(
        self, req: RouteToVertex.Request, res: RouteToVertex.Response
    ) -> RouteToVertex.Response:
        target = req.target_name
        # request.start 가 (0,0,0) 이면 현재 odom 사용
        if req.start.x == 0.0 and req.start.y == 0.0:
            cur = self._current_xy()
            if cur is None:
                res.success = False
                res.message = "no odom yet, pass non-zero start"
                return res
            sx, sy = cur
        else:
            sx, sy = req.start.x, req.start.y

        try:
            src = self._graph.nearest_vertex(sx, sy)
            seq = self._graph.route(src, target)
        except Exception as e:
            res.success = False
            res.message = str(e)
            return res

        res.success = True
        res.message = ""
        res.vertex_sequence = list(seq)
        # 총 거리
        total = 0.0
        for a, b in zip(seq[:-1], seq[1:]):
            va, vb = self._graph.vertices[a], self._graph.vertices[b]
            total += math.hypot(va.x - vb.x, va.y - vb.y)
        res.total_distance_m = float(total)
        return res

    # ──────── action: navigate_to_vertex ────────
    async def _act_navigate(
        self, gh: ServerGoalHandle
    ) -> NavigateToVertex.Result:
        target = gh.request.target_name
        result = NavigateToVertex.Result()

        cur = self._current_xy()
        if cur is None:
            gh.abort()
            result.success = False
            result.message = "no odom yet"
            return result

        try:
            src = self._graph.nearest_vertex(*cur)
            seq = self._graph.route(src, target)
        except Exception as e:
            gh.abort()
            result.success = False
            result.message = str(e)
            return result

        # vertex sequence → PoseStamped 리스트
        poses: list[PoseStamped] = []
        for name in seq:
            v = self._graph.vertices[name]
            ps = PoseStamped()
            ps.header.frame_id = self._frame_id
            ps.header.stamp = self.get_clock().now().to_msg()
            ps.pose.position.x = float(v.x)
            ps.pose.position.y = float(v.y)
            # yaw → quaternion (z = sin(yaw/2), w = cos(yaw/2))
            ps.pose.orientation.z = float(math.sin(v.yaw / 2.0))
            ps.pose.orientation.w = float(math.cos(v.yaw / 2.0))
            poses.append(ps)

        # nav2 FollowWaypoints 호출
        if not self._nav_ac.wait_for_server(timeout_sec=2.0):
            gh.abort()
            result.success = False
            result.message = f"nav2 action server '{self._follow_action}' not available"
            return result

        nav_goal = FollowWaypoints.Goal()
        nav_goal.poses = poses

        last_idx = 0

        def _on_nav_feedback(fb_msg) -> None:
            nonlocal last_idx
            idx = int(fb_msg.feedback.current_waypoint)
            last_idx = idx
            self._publish_feedback(gh, seq, idx)

        send_future = self._nav_ac.send_goal_async(
            nav_goal, feedback_callback=_on_nav_feedback
        )
        await send_future
        nav_gh = send_future.result()
        if not nav_gh.accepted:
            gh.abort()
            result.success = False
            result.message = "nav2 rejected goal"
            return result

        # 최종 결과 대기
        get_result_future = nav_gh.get_result_async()
        await get_result_future
        nav_result = get_result_future.result().result
        # FollowWaypoints.Result: missed_waypoints (uint32[])
        missed = list(getattr(nav_result, "missed_waypoints", []))

        if missed:
            gh.abort()
            result.success = False
            result.message = f"missed waypoints: {missed}"
            result.final_vertex = seq[last_idx] if last_idx < len(seq) else target
            return result

        gh.succeed()
        result.success = True
        result.message = ""
        result.final_vertex = target
        return result

    def _publish_feedback(
        self, gh: ServerGoalHandle, seq: list[str], idx: int
    ) -> None:
        idx = max(0, min(len(seq) - 1, idx))
        fb = NavigateToVertex.Feedback()
        fb.current_vertex = seq[idx]
        fb.sequence_index = int(idx)
        fb.sequence_total = len(seq)
        fb.progress = float(idx) / max(1, len(seq) - 1)
        gh.publish_feedback(fb)


def main() -> None:
    rclpy.init()
    node = GraphRouterNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
