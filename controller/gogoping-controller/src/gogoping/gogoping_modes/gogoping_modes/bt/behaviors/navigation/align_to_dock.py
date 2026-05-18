"""AlignToDock — 도크 등진 자세 (target yaw) 로 제자리 회전.

ReturnSubTree 의 2단계 (NavigateToVertex 직후, ReverseIntoDock 직전).
충전소입구 도착 시 robot 의 yaw 는 nav2 의 ``yaw_goal_tolerance=3.14`` 정책상
무작위 — 본 behavior 가 ``CHARGING_DOCK_TARGET_YAW`` 까지 cmd_vel.angular.z 로
회전 후 SUCCESS.

Blackboard:
  read:  ROBOT_POSE (AMCL yaw), CHARGING_DOCK_TARGET_YAW (rad)
  write: 없음

Topic publish: ``/gogoping/cmd_vel`` (geometry_msgs/Twist)

Status:
  RUNNING — 회전 중
  SUCCESS — |yaw_error| < tolerance 도달 (cmd_vel = 0 publish 후)
  FAILURE — timeout 초과 (cmd_vel = 0 publish 후) — main.py 가 fault trigger

ROS param:
  align_tolerance_rad (기본 0.05 ≈ 3°)
  align_angular_speed (기본 0.5 rad/s)
  align_timeout_sec   (기본 10.0)

terminate(INVALID): cmd_vel = 0 publish 보장 — 트리 중간 종료 시 robot 정지.
"""
from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Any

import py_trees
from py_trees.common import Access, Status

from ...blackboard import Keys

if TYPE_CHECKING:
    from ....context import Context


_DEFAULT_TOLERANCE_RAD = 0.05
_DEFAULT_ANGULAR_SPEED = 0.5
_DEFAULT_TIMEOUT_SEC = 10.0
_CMD_VEL_TOPIC = "/gogoping/cmd_vel"


def _wrap_to_pi(angle: float) -> float:
    """[-π, π] 로 정규화."""
    return math.atan2(math.sin(angle), math.cos(angle))


class AlignToDock(py_trees.behaviour.Behaviour):
    """블랙보드의 target yaw 까지 제자리 회전."""

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context
        self._tolerance = _DEFAULT_TOLERANCE_RAD
        self._angular_speed = _DEFAULT_ANGULAR_SPEED
        self._timeout_sec = _DEFAULT_TIMEOUT_SEC

        # ROS param 등록 — 이미 등록돼 있어도 안전 (idle_timeout_monitor 패턴)
        node = getattr(self.ctx, "node", None)
        if node is not None:
            for pname, default, setter in (
                ("align_tolerance_rad", _DEFAULT_TOLERANCE_RAD,
                 lambda v: setattr(self, "_tolerance", v)),
                ("align_angular_speed", _DEFAULT_ANGULAR_SPEED,
                 lambda v: setattr(self, "_angular_speed", v)),
                ("align_timeout_sec", _DEFAULT_TIMEOUT_SEC,
                 lambda v: setattr(self, "_timeout_sec", v)),
            ):
                try:
                    node.declare_parameter(pname, default)
                except Exception:
                    pass
                try:
                    v = float(node.get_parameter(pname).get_parameter_value().double_value)
                    if v > 0:
                        setter(v)
                except Exception:
                    pass

        self.bb = self.attach_blackboard_client(name=self.qualified_name)
        self.bb.register_key(key=Keys.ROBOT_POSE, access=Access.READ)
        self.bb.register_key(key=Keys.CHARGING_DOCK_TARGET_YAW, access=Access.READ)

        self._cmd_vel_pub: Any = None
        self._started_at: float | None = None

    def setup(self, **kwargs: Any) -> None:
        """``/gogoping/cmd_vel`` publisher 생성. node 미주입 시 외부 inject 대기."""
        node = kwargs.get("node") or getattr(self.ctx, "node", None)
        if node is None or self._cmd_vel_pub is not None:
            return
        try:
            from geometry_msgs.msg import Twist  # ROS 의존성 — setup 시점만
            self._cmd_vel_pub = node.create_publisher(Twist, _CMD_VEL_TOPIC, 10)
        except Exception:
            self._cmd_vel_pub = None

    def initialise(self) -> None:
        self._started_at = time.monotonic()

    def update(self) -> Status:
        try:
            pose = self.bb.get(Keys.ROBOT_POSE)
            current_yaw = float(pose["yaw"])
            target_yaw = float(self.bb.get(Keys.CHARGING_DOCK_TARGET_YAW))
        except Exception:
            self._publish_twist(0.0, 0.0)
            return Status.FAILURE

        error = _wrap_to_pi(target_yaw - current_yaw)
        if abs(error) <= self._tolerance:
            self._publish_twist(0.0, 0.0)
            return Status.SUCCESS

        # timeout
        if (
            self._started_at is not None
            and time.monotonic() - self._started_at >= self._timeout_sec
        ):
            self._publish_twist(0.0, 0.0)
            return Status.FAILURE

        # 부호로 회전 방향, 속도는 고정
        angular = self._angular_speed if error > 0 else -self._angular_speed
        self._publish_twist(0.0, angular)
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        # 트리 중간 종료 시 robot 멈추기 — idempotent
        self._publish_twist(0.0, 0.0)

    def _publish_twist(self, linear_x: float, angular_z: float) -> None:
        pub = self._cmd_vel_pub
        if pub is None:
            return
        try:
            from geometry_msgs.msg import Twist
            msg = Twist()
            msg.linear.x = linear_x
            msg.angular.z = angular_z
            pub.publish(msg)
        except Exception:
            pass
