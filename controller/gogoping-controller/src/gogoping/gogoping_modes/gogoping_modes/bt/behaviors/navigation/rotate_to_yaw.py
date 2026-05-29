"""RotateToYaw — 현재 위치에서 target yaw 로 제자리 회전 (cmd_vel.angular.z 직접).

AlignToDock 와 **동일 원리**. nav2 의 ``general_goal_checker`` 가 yaw 를 무시
(``yaw_goal_tolerance=3.14``, "도착 후 회전 안 함" 정책)하기 때문에 NavigateToPose 로는
같은 (x,y) + 다른 yaw goal 이 즉시 SUCCESS 처리되어 **회전이 일어나지 않는다**. 그래서
``ROBOT_POSE`` 의 yaw 를 읽어 ``cmd_vel.angular.z`` 를 직접 publish 해 target yaw 까지
제자리 회전 → 오차가 tolerance 안에 들면 정지 후 SUCCESS.

cmd_vel 직접 방식이라 **goal_checker 를 건드리지 않으므로 일반주행/다른 노드엔 영향 0**.
(RotateToYaw 는 숨바꼭질에서만 사용 — BT_hide_and_seek_sub: 0° / 180°.)

Blackboard:
  read:  ROBOT_POSE (AMCL yaw)
Topic publish: ``/gogoping/cmd_vel`` (geometry_msgs/Twist)
  — modes 노드 remap (`/gogoping/cmd_vel:=/gogoping/cmd_vel_raw`) 으로 safety_filter 경유.

Status:
  RUNNING — 회전 중
  SUCCESS — |yaw_error| <= tolerance (cmd_vel = 0 publish 후)
  FAILURE — ROBOT_POSE/yaw 없음 또는 timeout (cmd_vel = 0 publish 후)

terminate(INVALID 등): cmd_vel = 0 publish 보장 — 트리 중간 종료 시 robot 정지.

| 파일 | bt/behaviors/navigation/rotate_to_yaw.py |
| Used in | BT_hide_and_seek_sub (step_move_to_play 끝 / step_recruit 끝) |
"""
from __future__ import annotations

import math
import time
from typing import Any

import py_trees
from py_trees.common import Access, Status

from ...blackboard import Keys


_DEFAULT_TOLERANCE_RAD = 0.1     # ~5.7° — "벽 보고 세기" 용도라 정밀 불필요
_DEFAULT_ANGULAR_SPEED = 0.5     # rad/s (AlignToDock 와 동일)
_DEFAULT_TIMEOUT_SEC = 30.0
_CMD_VEL_TOPIC = "/gogoping/cmd_vel"


def _wrap_to_pi(angle: float) -> float:
    """[-π, π] 로 정규화."""
    return math.atan2(math.sin(angle), math.cos(angle))


class RotateToYaw(py_trees.behaviour.Behaviour):
    def __init__(
        self,
        name: str,
        target_yaw: float,
        tolerance_rad: float = _DEFAULT_TOLERANCE_RAD,
        angular_speed: float = _DEFAULT_ANGULAR_SPEED,
        timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
    ) -> None:
        super().__init__(name)
        self._target_yaw = float(target_yaw)
        self._tolerance = float(tolerance_rad)
        self._angular_speed = float(angular_speed)
        self._timeout_sec = float(timeout_sec)
        self._node: Any = None
        self._cmd_vel_pub: Any = None
        self._debug_events: Any = None
        self._started_at: float | None = None
        self.bb = self.attach_blackboard_client(name=self.qualified_name)
        self.bb.register_key(key=Keys.ROBOT_POSE, access=Access.READ)

    def setup(self, **kwargs: Any) -> None:
        """cmd_vel publisher 확보 — ctx.cmd_vel_pub 우선, 없으면 node 로 생성."""
        self._node = kwargs.get("node")
        self._debug_events = kwargs.get("debug_events")
        if self._cmd_vel_pub is not None:
            return
        ctx = kwargs.get("context")
        shared = getattr(ctx, "cmd_vel_pub", None) if ctx is not None else None
        if shared is not None:
            self._cmd_vel_pub = shared
            return
        if self._node is None:
            return
        try:
            from geometry_msgs.msg import Twist
            self._cmd_vel_pub = self._node.create_publisher(Twist, _CMD_VEL_TOPIC, 10)
        except Exception:
            self._cmd_vel_pub = None

    def _dbg(self, msg: str, level: str = "info") -> None:
        if self._debug_events is not None:
            try:
                self._debug_events.event("RotateToYaw", msg, level=level)
            except Exception:
                pass

    def initialise(self) -> None:
        self._started_at = time.monotonic()
        self._dbg(f"start → target_yaw={self._target_yaw:.3f}")

    def update(self) -> Status:
        try:
            pose = self.bb.get(Keys.ROBOT_POSE)
            current_yaw = float(pose["yaw"])
        except Exception:
            self._publish_twist(0.0, 0.0)
            self.feedback_message = "ROBOT_POSE/yaw 없음"
            return Status.FAILURE

        error = _wrap_to_pi(self._target_yaw - current_yaw)
        if abs(error) <= self._tolerance:
            self._publish_twist(0.0, 0.0)
            self._dbg(f"SUCCESS yaw={current_yaw:.3f} (err={error:.3f})")
            return Status.SUCCESS

        if (
            self._started_at is not None
            and time.monotonic() - self._started_at >= self._timeout_sec
        ):
            self._publish_twist(0.0, 0.0)
            self._dbg(f"TIMEOUT err={error:.3f}", level="warn")
            self.feedback_message = "rotate timeout"
            return Status.FAILURE

        # 부호로 회전 방향, 속도는 고정 (AlignToDock 와 동일).
        angular = self._angular_speed if error > 0 else -self._angular_speed
        self._publish_twist(0.0, angular)
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        # 트리 중간 종료 시 robot 멈추기 — idempotent.
        self._publish_twist(0.0, 0.0)

    def _publish_twist(self, linear_x: float, angular_z: float) -> None:
        pub = self._cmd_vel_pub
        if pub is None:
            return
        try:
            from geometry_msgs.msg import Twist
            msg = Twist()
            msg.linear.x = float(linear_x)
            msg.angular.z = float(angular_z)
            pub.publish(msg)
        except Exception:
            pass
