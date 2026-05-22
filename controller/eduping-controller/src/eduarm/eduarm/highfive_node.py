#!/usr/bin/env python3
"""EduPing high-five controller — hand point → 5cm 앞 IK → JointTrajectory.

파이프라인:
  /eduping/highfive/hand_point  (PointStamped, frame_id=d435_depth_optical_frame)
    → tf2 (world — MoveIt openarm_bimanual URDF root; base_link 없음)
    → approach = hand - 5cm * unit(hand - shoulder)    (안전 stop-short)
    → 좌/우 arm 선택 (y > 0 → left)
    → MoveIt /compute_ik (group=left_arm|right_arm, 여러 quaternion 시도)
    → JointTrajectory (current → target, ~2.5s 선형)
    → /eduping/joint_trajectory  (sim_twin_node 또는 실물 controller 가 forward)
  + TF broadcast 'eduping_hand_target' (시각 확인용, 변환된 hand 위치)

KDL plugin 은 full-pose IK 만 가능 — 적절한 EE orientation 추정이 안 되면 fail.
identity / forward / rotated 등 여러 quaternion 을 순차 시도해 첫 성공값 사용.

쓰로틀: 같은 hand point 가 10Hz 로 들어와도 모션 재계획은 최소 1초 간격.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import rclpy
from builtin_interfaces.msg import Duration as DurationMsg
from geometry_msgs.msg import (
    Point, PointStamped, Pose, PoseStamped, Quaternion, TransformStamped,
)
from moveit_msgs.msg import (
    MoveItErrorCodes, PositionIKRequest, RobotState,
)
from moveit_msgs.srv import GetPositionIK
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import JointState
from tf2_geometry_msgs import do_transform_point
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
import tf2_ros

from .joint_names import OPENARM_JOINT_NAMES


# MoveItConfigsBuilder 가 v10 bimanual URDF 를 쓰며 root 는 world (base_link 미사용).
BASE_FRAME = "world"
HAND_TARGET_FRAME = "eduping_hand_target"

LEFT_ARM_GROUP = "left_arm"
RIGHT_ARM_GROUP = "right_arm"
LEFT_EE_LINK = "openarm_left_link7"
RIGHT_EE_LINK = "openarm_right_link7"

LEFT_JOINT_NAMES = [f"openarm_left_joint{i}" for i in range(1, 8)]
RIGHT_JOINT_NAMES = [f"openarm_right_joint{i}" for i in range(1, 8)]

# Approach: hand 에서 shoulder 방향으로 5cm 후퇴
APPROACH_PULLBACK_M = 0.05
# 어깨 위치 (URDF v10.urdf.xacro 의 right/left_arm_base_xyz 와 일치)
LEFT_SHOULDER_BASE = (0.0, 0.031, 0.698)
RIGHT_SHOULDER_BASE = (0.0, -0.031, 0.698)
# Workspace 거친 가드 — 어깨에서 거리만 (OpenArm home EE 는 world x≈0, y/z 로 전방).
MAX_REACH_M = 0.85
MIN_REACH_M = 0.12
# 재계획 — 모션 끝날 때까지 + approach 가 충분히 움직였을 때만.
MIN_REPLAN_INTERVAL_S = 2.0
MIN_APPROACH_MOVE_M = 0.10
# y 부호 경계 히스테리시스 — 손이 중앙 근처에서 좌/우 팔이 바뀌며 flicker 방지.
ARM_Y_LEFT_M = 0.08
ARM_Y_RIGHT_M = -0.08
# 모션 시간 (current → target 선형).
TRAJECTORY_DURATION_S = 2.0
IK_TIMEOUT_S = 1.0

# KDL plugin: full pose IK only. Home FK orientation (x=1,w=0) succeeds; identity fails.
_LEFT_EE_NOMINAL_QUAT = (1.0, 0.0, 0.0, 0.0)
_RIGHT_EE_NOMINAL_QUAT = (1.0, 0.0, 0.0, 0.0)

_FALLBACK_QUATS: list[tuple[float, float, float, float]] = [
    (0.0, 0.7071, 0.0, 0.7071),
    (0.7071, 0.0, 0.0, 0.7071),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, -0.7071, 0.0, 0.7071),
]


def _quat_z_to_unit(ux: float, uy: float, uz: float) -> tuple[float, float, float, float]:
    """(x,y,z,w): local +Z → unit direction (ux,uy,uz)."""
    dot = max(-1.0, min(1.0, uz))
    if dot > 0.9999:
        return (0.0, 0.0, 0.0, 1.0)
    if dot < -0.9999:
        return (1.0, 0.0, 0.0, 0.0)
    ax, ay, az = -uy, ux, 0.0
    norm = math.sqrt(ax * ax + ay * ay + az * az)
    if norm < 1e-9:
        return (0.0, 0.0, 0.0, 1.0)
    ax, ay, az = ax / norm, ay / norm, az / norm
    angle = math.acos(dot)
    half = angle * 0.5
    s = math.sin(half)
    return (ax * s, ay * s, az * s, math.cos(half))


def _ik_orientation_candidates(
    arm: _ArmConfig,
    target: tuple[float, float, float],
) -> list[tuple[float, float, float, float]]:
    """Nominal EE (home FK) first, then look-at + fixed fallbacks."""
    dx = target[0] - arm.shoulder[0]
    dy = target[1] - arm.shoulder[1]
    dz = target[2] - arm.shoulder[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    out: list[tuple[float, float, float, float]] = [arm.ee_nominal_quat]
    if dist >= 1e-3:
        ux, uy, uz = dx / dist, dy / dist, dz / dist
        out.extend([
            _quat_z_to_unit(ux, uy, uz),
            _quat_z_to_unit(-ux, -uy, -uz),
        ])
    out.extend(_FALLBACK_QUATS)
    return out


@dataclass
class _ArmConfig:
    group: str
    ee_link: str
    joint_names: list[str]
    shoulder: tuple[float, float, float]
    ee_nominal_quat: tuple[float, float, float, float]


LEFT_ARM = _ArmConfig(
    LEFT_ARM_GROUP, LEFT_EE_LINK, LEFT_JOINT_NAMES, LEFT_SHOULDER_BASE, _LEFT_EE_NOMINAL_QUAT,
)
RIGHT_ARM = _ArmConfig(
    RIGHT_ARM_GROUP, RIGHT_EE_LINK, RIGHT_JOINT_NAMES, RIGHT_SHOULDER_BASE, _RIGHT_EE_NOMINAL_QUAT,
)


class HighfiveNode(Node):
    def __init__(self) -> None:
        super().__init__("highfive_node")
        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self)
        self._tf_broadcaster = tf2_ros.TransformBroadcaster(self)

        self._sub = self.create_subscription(
            PointStamped, "/eduping/highfive/hand_point",
            self._on_hand_point, 10,
        )
        self._traj_pub = self.create_publisher(
            JointTrajectory, "/eduping/joint_trajectory", 10,
        )
        self._js_sub = self.create_subscription(
            JointState, "/joint_states", self._on_joint_state, 10,
        )
        self._last_joint_state: Optional[JointState] = None
        self._joint_pos: dict[str, float] = {n: 0.0 for n in OPENARM_JOINT_NAMES}

        self._ik_cli = self.create_client(GetPositionIK, "/compute_ik")

        self._last_plan_at_s = 0.0
        self._motion_busy_until_s = 0.0
        self._last_approach: Optional[tuple[float, float, float]] = None
        self._last_arm: Optional[_ArmConfig] = None
        # 연속 재계획 — 새 요청 시 카운터 증가, 이전 in-flight IK 응답은 stale 로 폐기.
        self._current_request_id = 0

        self.get_logger().info(
            "highfive_node ready — "
            "sub /eduping/highfive/hand_point "
            "pub /eduping/joint_trajectory "
            f"ik /compute_ik (replan {MIN_REPLAN_INTERVAL_S}s)"
        )

    def _on_joint_state(self, msg: JointState) -> None:
        for name, pos in zip(msg.name, msg.position):
            if name in self._joint_pos:
                self._joint_pos[name] = float(pos)
        merged = JointState()
        merged.header = msg.header
        merged.name = list(OPENARM_JOINT_NAMES)
        merged.position = [self._joint_pos[n] for n in OPENARM_JOINT_NAMES]
        self._last_joint_state = merged

    def _on_hand_point(self, msg: PointStamped) -> None:
        # 1. TF: optical → world
        try:
            tform = self._tf_buffer.lookup_transform(
                BASE_FRAME, msg.header.frame_id, Time(),
                timeout=Duration(seconds=0.1),
            )
        except (tf2_ros.LookupException, tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException) as exc:
            self.get_logger().warn(
                f"TF {msg.header.frame_id} → {BASE_FRAME} 실패: {exc}",
                throttle_duration_sec=2.0,
            )
            return

        transformed = do_transform_point(msg, tform)
        hand_x, hand_y, hand_z = (
            transformed.point.x, transformed.point.y, transformed.point.z,
        )
        self._broadcast_hand_target(hand_x, hand_y, hand_z)

        now_s = self.get_clock().now().nanoseconds * 1e-9
        if now_s < self._motion_busy_until_s:
            return
        if now_s - self._last_plan_at_s < MIN_REPLAN_INTERVAL_S:
            return

        # arm 선택 (히스테리시스)
        if hand_y >= ARM_Y_LEFT_M:
            arm = LEFT_ARM
            self._last_arm = LEFT_ARM
        elif hand_y <= ARM_Y_RIGHT_M:
            arm = RIGHT_ARM
            self._last_arm = RIGHT_ARM
        elif self._last_arm is not None:
            arm = self._last_arm
        else:
            arm = LEFT_ARM if hand_y >= 0.0 else RIGHT_ARM
            self._last_arm = arm
        sx, sy, sz = arm.shoulder
        dx, dy, dz = hand_x - sx, hand_y - sy, hand_z - sz
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist < MIN_REACH_M:
            return
        if dist > MAX_REACH_M:
            self.get_logger().warn(
                f"hand {dist:.2f}m > 도달 한계 {MAX_REACH_M}m — skip",
                throttle_duration_sec=2.0,
            )
            return

        # 4. approach = hand - 5cm * unit(hand - shoulder)
        if dist < 1e-3:
            return  # degenerate
        ux, uy, uz = dx / dist, dy / dist, dz / dist
        ax = hand_x - APPROACH_PULLBACK_M * ux
        ay = hand_y - APPROACH_PULLBACK_M * uy
        az = hand_z - APPROACH_PULLBACK_M * uz

        if self._last_approach is not None:
            la = self._last_approach
            move = math.sqrt(
                (ax - la[0]) ** 2 + (ay - la[1]) ** 2 + (az - la[2]) ** 2,
            )
            if move < MIN_APPROACH_MOVE_M:
                return

        # IK 요청 — 여러 quaternion 시도, 첫 성공값 사용. async chain.
        if not self._ik_cli.service_is_ready():
            self.get_logger().warn(
                "/compute_ik 미준비 — move_group 띄웠는지 확인",
                throttle_duration_sec=2.0,
            )
            return
        if self._last_joint_state is None:
            self.get_logger().warn("joint_states 아직 수신 안 됨", throttle_duration_sec=2.0)
            return

        self._current_request_id += 1
        quats = _ik_orientation_candidates(arm, (ax, ay, az))
        self._try_ik(arm, (ax, ay, az), 0, self._current_request_id, quats)

    def _try_ik(
        self,
        arm: _ArmConfig,
        position: tuple[float, float, float],
        quat_idx: int,
        request_id: int,
        quats: list[tuple[float, float, float, float]],
    ) -> None:
        if request_id != self._current_request_id:
            return   # 더 새로운 요청이 들어왔으면 이 시도 chain 도 폐기.
        if quat_idx >= len(quats):
            self.get_logger().warn(
                f"{arm.group}: 모든 candidate orientation 에서 IK fail — skip "
                f"(approach=({position[0]:.2f},{position[1]:.2f},{position[2]:.2f}))",
            )
            return
        qx, qy, qz, qw = quats[quat_idx]
        req = GetPositionIK.Request()
        ik = PositionIKRequest()
        ik.group_name = arm.group
        ik.ik_link_name = arm.ee_link
        ik.avoid_collisions = False
        ps = PoseStamped()
        ps.header.frame_id = BASE_FRAME
        ps.header.stamp = self.get_clock().now().to_msg()
        ps.pose = Pose(
            position=Point(x=position[0], y=position[1], z=position[2]),
            orientation=Quaternion(x=qx, y=qy, z=qz, w=qw),
        )
        ik.pose_stamped = ps
        ik.robot_state = self._make_robot_state()
        ik.timeout = DurationMsg(sec=0, nanosec=int(IK_TIMEOUT_S * 1e9))
        req.ik_request = ik

        future = self._ik_cli.call_async(req)
        future.add_done_callback(
            lambda fut: self._on_ik_response(
                fut, arm, position, quat_idx, request_id, quats,
            )
        )

    def _on_ik_response(
        self,
        future,
        arm: _ArmConfig,
        position: tuple[float, float, float],
        quat_idx: int,
        request_id: int,
        quats: list[tuple[float, float, float, float]],
    ) -> None:
        if request_id != self._current_request_id:
            return   # stale — 더 새로운 요청이 이미 진행 중.
        try:
            response = future.result()
        except Exception as exc:
            self.get_logger().error(f"IK service error: {exc}")
            return
        if response is None:
            return
        if response.error_code.val != MoveItErrorCodes.SUCCESS:
            # 다음 quaternion 시도 (같은 request_id 안에서)
            self._try_ik(arm, position, quat_idx + 1, request_id, quats)
            return

        # 성공 — joint 추출
        sol = response.solution.joint_state
        name_to_pos = dict(zip(sol.name, sol.position))
        target = [name_to_pos.get(jn, 0.0) for jn in arm.joint_names]
        self.get_logger().info(
            f"{arm.group} IK ok (quat_idx={quat_idx}) → {[f'{v:.2f}' for v in target]}",
        )
        self._last_approach = position
        self._publish_trajectory(arm, target)

    def _publish_trajectory(self, arm: _ArmConfig, target: list[float]) -> None:
        """현재 joint_state 에서 target 까지 2-point 선형 trajectory (16 joint 전체).

        비활성 팔은 현재 pose 유지 — sim_twin 이 다른 팔을 0 으로 리셋하지 않게.
        """
        if self._last_joint_state is None:
            return
        name_to_pos = dict(zip(
            self._last_joint_state.name, self._last_joint_state.position,
        ))
        current_full = [float(name_to_pos.get(jn, 0.0)) for jn in OPENARM_JOINT_NAMES]
        target_full = list(current_full)
        for jn, val in zip(arm.joint_names, target):
            target_full[OPENARM_JOINT_NAMES.index(jn)] = float(val)

        traj = JointTrajectory()
        traj.joint_names = list(OPENARM_JOINT_NAMES)
        traj.header.stamp = self.get_clock().now().to_msg()

        p0 = JointTrajectoryPoint()
        p0.positions = current_full
        p0.time_from_start = DurationMsg(sec=0, nanosec=0)
        p1 = JointTrajectoryPoint()
        p1.positions = target_full
        p1.time_from_start = DurationMsg(
            sec=int(TRAJECTORY_DURATION_S),
            nanosec=int((TRAJECTORY_DURATION_S % 1) * 1e9),
        )
        traj.points = [p0, p1]
        self._traj_pub.publish(traj)
        now_s = self.get_clock().now().nanoseconds * 1e-9
        self._last_plan_at_s = now_s
        self._motion_busy_until_s = now_s + TRAJECTORY_DURATION_S + 0.3
        self.get_logger().info(
            f"{arm.group} trajectory published ({TRAJECTORY_DURATION_S:.1f}s)",
        )

    def _make_robot_state(self) -> RobotState:
        rs = RobotState()
        js = JointState()
        js.name = list(OPENARM_JOINT_NAMES)
        js.position = [self._joint_pos[n] for n in OPENARM_JOINT_NAMES]
        rs.joint_state = js
        return rs

    def _broadcast_hand_target(self, x: float, y: float, z: float) -> None:
        t = TransformStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = BASE_FRAME
        t.child_frame_id = HAND_TARGET_FRAME
        t.transform.translation.x = x
        t.transform.translation.y = y
        t.transform.translation.z = z
        t.transform.rotation.w = 1.0
        self._tf_broadcaster.sendTransform(t)


def main(args=None) -> int:
    rclpy.init(args=args)
    node = HighfiveNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    main()
