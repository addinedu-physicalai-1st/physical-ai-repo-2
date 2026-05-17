"""로봇 pose (map frame) 토픽 구독 → blackboard.ROBOT_POSE 갱신.

**Frame: map (not odom)** — AMCL 의 localization 결과를 받음. map.yaml 영역 (origin +
resolution) 과 직접 비교 가능 → ``map_boundary_monitor`` 의 정확한 IN/OUT 판별.

토픽: ``/amcl_pose`` (root namespace 절대 경로). 메시지: ``geometry_msgs/PoseWithCovarianceStamped``.

운영(실물 Pi) + sim 둘 다: nav2 stack 의 ``nav2_amcl`` 노드가 publisher. sim_with_nav2.launch.xml
의 AMCL 이 root namespace 에 띄워져 있어서 토픽이 ``/amcl_pose`` (gogoping/amcl_pose 아님).

추출: ``msg.pose.pose`` 의 (x, y) + quaternion → yaw 변환. ``Keys.ROBOT_POSE`` 로
``{"x": float, "y": float, "yaw": float}`` 저장 — **map frame**.

**디버그 override 지원** — ``blackboard.POSE_OVERRIDE_ACTIVE`` 가 True 면 _on_pose 가
매 메시지마다 W 를 skip. command_listener 의 SetRobotPose.srv 가 admin UI 의
PoseDebugPanel 입력을 받아 override 활성화/해제.

이전 ``OdomSubscriber`` 에서 rename + 토픽 교체. /gogoping/odom 은 odom frame 이라
spawn (0.2, -7) 같은 map-frame 좌표를 못 봤음. /amcl_pose 로 교체 후 정확한 map-frame
좌표 추적 + RViz 2D Pose Estimate 도 정상 반영.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Access
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from ..bt.blackboard import Keys

if TYPE_CHECKING:
    import rclpy.node


class PoseSubscriber:
    """``/amcl_pose`` 구독 + blackboard.ROBOT_POSE W (map frame)."""

    TOPIC = "/amcl_pose"   # 절대경로 — root namespace 의 nav2_amcl 와 일치
    QOS_DEPTH = 10

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
        self._bb = py_trees.blackboard.Client(name="PoseSubscriber")
        self._bb.register_key(key=Keys.ROBOT_POSE, access=Access.WRITE)
        self._bb.register_key(key=Keys.POSE_OVERRIDE_ACTIVE, access=Access.READ)
        # AMCL 은 default QoS (RELIABLE + VOLATILE) — 명시적 매칭은 없어도 OK.
        # 다만 안정성 위해 QoSProfile 명시 (history KEEP_LAST + depth 10).
        qos = QoSProfile(
            depth=self.QOS_DEPTH,
            durability=DurabilityPolicy.VOLATILE,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self._sub = node.create_subscription(
            PoseWithCovarianceStamped,
            self.TOPIC,
            self._on_pose,
            qos,
        )

    def _on_pose(self, msg: PoseWithCovarianceStamped) -> None:
        # 디버그 override 가 active 이면 amcl 무시 — blackboard.ROBOT_POSE 유지
        try:
            if bool(self._bb.get(Keys.POSE_OVERRIDE_ACTIVE)):
                return
        except (KeyError, TypeError):
            pass

        p = msg.pose.pose.position
        q = msg.pose.pose.orientation
        # quaternion → yaw (z 축 회전만 추출)
        yaw = math.atan2(
            2.0 * (q.w * q.z + q.x * q.y),
            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
        )
        self._bb.set(
            Keys.ROBOT_POSE,
            {"x": float(p.x), "y": float(p.y), "yaw": float(yaw)},
        )
