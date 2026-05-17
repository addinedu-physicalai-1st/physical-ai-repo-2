"""오도메트리 토픽 구독 → blackboard.ROBOT_POSE 갱신.

토픽: ``odom`` (상대 — gogoping_modes 노드 namespace 가 ``gogoping`` 이라 절대는
``/gogoping/odom``). 메시지: ``nav_msgs/Odometry``.

운영(실물 Pi): ``vicpinky_bringup`` 의 driver 가 ``/gogoping/odom`` 발행.
sim: gazebo + Vic Pinky 플러그인이 동일 경로 발행.

추출: ``msg.pose.pose`` 의 (x, y) + quaternion → yaw 변환. ``Keys.ROBOT_POSE`` 로
``{"x": float, "y": float, "yaw": float}`` 저장. ``map_boundary_monitor`` 가 R.

Yaw 변환은 표준 quaternion → euler — scipy 없이 atan2 만으로.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Access
from nav_msgs.msg import Odometry

from ..bt.blackboard import Keys

if TYPE_CHECKING:
    import rclpy.node


class OdomSubscriber:
    """``/gogoping/odom`` 구독 + blackboard.ROBOT_POSE W."""

    def __init__(self, node: "rclpy.node.Node"):
        self.node = node
        self._bb = py_trees.blackboard.Client(name="OdomSubscriber")
        self._bb.register_key(key=Keys.ROBOT_POSE, access=Access.WRITE)
        self._sub = node.create_subscription(
            Odometry,
            "odom",
            self._on_odom,
            10,
        )

    def _on_odom(self, msg: Odometry) -> None:
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
