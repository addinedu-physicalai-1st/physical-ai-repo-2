"""gogoping_follow ROS 노드 — tracking_state + scan + tf → Nav2 NavigateToPose.

control loop (NAV2_GOAL_HZ):
1. 최신 tracking_state 가 stale 또는 mode != "tracking" → cancel goal + return
2. bbox bearing + LiDAR 거리 fusion → target world pose
3. target 의 1.5m 뒤 위치 = goal
4. 이전 goal 과 0.3m 이상 차이 시에만 새 goal send (Nav2 reissue spam 회피)
"""
from __future__ import annotations

import math
import time

import rclpy
import tf2_geometry_msgs  # noqa: F401 — import side-effect 로 PoseStamped 변환 등록
from geometry_msgs.msg import Pose, PoseWithCovarianceStamped
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import LaserScan
from tf2_ros import Buffer, TransformListener

from gogoping_msgs.msg import FollowTarget, TrackingState

from gogoping_follow.config import (
    GOAL_CHANGE_THRESHOLD_M,
    NAV2_GOAL_HZ,
    STATE_STALE_TIMEOUT_S,
)
from gogoping_follow.nav2_client import Nav2Client
from gogoping_follow.target_pose_estimator import estimate_follow_goal


class FollowNode(Node):
    def __init__(self) -> None:
        super().__init__("gogoping_follow_node")

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._nav2 = Nav2Client(self)

        self._target_id: str = ""
        self._last_state: TrackingState | None = None
        self._last_state_ts: float = 0.0
        self._last_scan: LaserScan | None = None
        self._robot_map_pose: Pose | None = None
        self._last_goal: Pose | None = None

        self.create_subscription(
            TrackingState, "/gogoping/tracking_state", self._on_tracking_state, 10,
        )
        # LiDAR 는 sllidar_node 가 /gogoping/scan namespace 로 publish.
        # AMCL/Nav2 와 동일 토픽 사용 — laser_scan_polygon_filter 거친 scan_filtered 보다
        # raw scan 이 LiDAR fusion 의 정면 거리 추정에 더 단순.
        self.create_subscription(LaserScan, "/gogoping/scan", self._on_scan, 10)
        self.create_subscription(
            FollowTarget, "/gogoping/follow_target", self._on_follow_target, 10,
        )
        # AMCL publisher 가 TRANSIENT_LOCAL durability — late joiner (우리) 도 마지막 pose
        # 한 번은 받도록 같은 QoS 로 구독. AMCL 은 robot 정지 시 publish 멈춤 → 그 사이
        # follow_node 시작하면 last cached msg 라도 받아야 _robot_map_pose set 됨.
        amcl_qos = QoSProfile(
            depth=10,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(
            PoseWithCovarianceStamped, "/amcl_pose", self._on_amcl_pose, amcl_qos,
        )

        self.create_timer(1.0 / NAV2_GOAL_HZ, self._tick_control)

        self.get_logger().info(
            "FollowNode initialized — Nav2 NavigateToPose 액션 client. "
            "waiting for /gogoping/tracking_state + /scan + /amcl_pose."
        )

    # ---------- subscriptions ----------
    def _on_follow_target(self, msg: FollowTarget) -> None:
        if not msg.teacher_id:
            self._target_id = ""
            self._last_state = None
            self._nav2.cancel_current()
            self._last_goal = None
            self.get_logger().info("FollowTarget stop — goal cancel")
            return
        self._target_id = msg.teacher_id
        self.get_logger().info(
            f"FollowTarget start: {msg.teacher_name} ({msg.teacher_id[:8]}...)"
        )

    def _on_tracking_state(self, msg: TrackingState) -> None:
        self._last_state = msg
        self._last_state_ts = time.time()

    def _on_scan(self, msg: LaserScan) -> None:
        self._last_scan = msg

    def _on_amcl_pose(self, msg: PoseWithCovarianceStamped) -> None:
        self._robot_map_pose = msg.pose.pose

    # ---------- control loop ----------
    def _tick_control(self) -> None:
        if not self._target_id:
            return

        state = self._last_state
        now = time.time()
        stale = state is None or (now - self._last_state_ts) > STATE_STALE_TIMEOUT_S
        not_tracking = state is None or state.mode != "tracking" or not state.matched

        if stale or not_tracking:
            if self._last_goal is not None:
                self._nav2.cancel_current()
                self._last_goal = None
            return

        assert state is not None
        estimate = estimate_follow_goal(
            angle_deg=float(state.angle_deg),
            scan=self._last_scan,
            tf_buffer=self._tf_buffer,
            robot_map_pose=self._robot_map_pose,
        )
        if estimate is None:
            return

        if self._last_goal is None or _pose_distance(self._last_goal, estimate.goal) >= GOAL_CHANGE_THRESHOLD_M:
            self._nav2.send_goal(estimate.goal)
            self._last_goal = estimate.goal


def _pose_distance(a: Pose, b: Pose) -> float:
    return math.hypot(
        b.position.x - a.position.x,
        b.position.y - a.position.y,
    )


def main() -> None:
    rclpy.init()
    node = FollowNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
