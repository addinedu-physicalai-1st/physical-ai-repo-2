"""ReverseIntoDock — 고정 시간 동안 cmd_vel.linear.x 음수 publish (후진 진입).

ReturnSubTree 의 3단계 (AlignToDock 직후). 충전소입구에서 도크 등진 자세로 정렬된
상태에서 단순히 N초 동안 뒤로 이동 — 자동 도킹 (접점 감지 등) 은 발표 단계 외 범위라
시간 기반.

Topic publish: ``/gogoping/cmd_vel`` (geometry_msgs/Twist)

Status:
  RUNNING — 후진 중 (elapsed < duration)
  SUCCESS — elapsed >= duration (cmd_vel = 0 publish 후)

ROS param:
  reverse_duration_sec (기본 10.0) — 충전소-충전소입구 약 1m, -0.1 m/s 가정
  reverse_linear_x     (기본 -0.1) — 음수 = 후진

terminate(INVALID): cmd_vel = 0 publish — 트리 중간 종료 시 정지.

설계 노트: 본 behavior 는 SUCCESS 후에도 OneShot decorator 로 감싸지므로 재실행 X.
사람이 admin UI 의 디버그 버튼으로 ``docked`` trigger 발사 → CHARGING 전이.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import py_trees
from py_trees.common import Status

if TYPE_CHECKING:
    from ....context import Context


_DEFAULT_DURATION_SEC = 10.0
_DEFAULT_LINEAR_X = -0.1
_CMD_VEL_TOPIC = "/gogoping/cmd_vel"


class ReverseIntoDock(py_trees.behaviour.Behaviour):
    """N초 후진 후 SUCCESS."""

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context
        self._duration_sec = _DEFAULT_DURATION_SEC
        self._linear_x = _DEFAULT_LINEAR_X

        node = getattr(self.ctx, "node", None)
        if node is not None:
            for pname, default, setter in (
                ("reverse_duration_sec", _DEFAULT_DURATION_SEC,
                 lambda v: setattr(self, "_duration_sec", v)),
                ("reverse_linear_x", _DEFAULT_LINEAR_X,
                 lambda v: setattr(self, "_linear_x", v)),
            ):
                try:
                    node.declare_parameter(pname, default)
                except Exception:
                    pass
                try:
                    v = float(node.get_parameter(pname).get_parameter_value().double_value)
                    setter(v)
                except Exception:
                    pass

        self._cmd_vel_pub: Any = None
        self._started_at: float | None = None

    def setup(self, **kwargs: Any) -> None:
        node = kwargs.get("node") or getattr(self.ctx, "node", None)
        if node is None or self._cmd_vel_pub is not None:
            return
        try:
            from geometry_msgs.msg import Twist
            self._cmd_vel_pub = node.create_publisher(Twist, _CMD_VEL_TOPIC, 10)
        except Exception:
            self._cmd_vel_pub = None

    def initialise(self) -> None:
        self._started_at = time.monotonic()

    def update(self) -> Status:
        if self._started_at is None:
            self._started_at = time.monotonic()

        elapsed = time.monotonic() - self._started_at
        if elapsed >= self._duration_sec:
            self._publish_twist(0.0, 0.0)
            return Status.SUCCESS

        self._publish_twist(self._linear_x, 0.0)
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
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
