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
from dataclasses import dataclass
from typing import Any

import py_trees
from py_trees.common import Access, Status

from ...blackboard import Keys


_DEFAULT_TOLERANCE_RAD = 0.1     # ~5.7° — "벽 보고 세기" 용도라 정밀 불필요
_DEFAULT_ANGULAR_SPEED = 0.5     # rad/s — 멀 때 회전 속도 상한 (AlignToDock 와 동일)
_DEFAULT_KP = 1.5                # rad/s per rad — 목표 근처 비례 감속 (error 0.33rad~ 부터 감속)
_DEFAULT_MIN_SPEED = 0.12        # rad/s — 정지마찰 floor (밴드 직전 stall 방지)
_DEFAULT_TIMEOUT_SEC = 30.0
_CMD_VEL_TOPIC = "/gogoping/cmd_vel"


def _wrap_to_pi(angle: float) -> float:
    """[-π, π] 로 정규화."""
    return math.atan2(math.sin(angle), math.cos(angle))


@dataclass
class RotateCmd:
    reached: bool       # |error| <= tolerance → 도달, 정지
    angular_z: float    # rad/s — 회전 명령 (reached 면 0.0)


def compute_rotate_cmd(
    error: float,
    tolerance: float,
    kp: float,
    min_speed: float,
    max_speed: float,
) -> RotateCmd:
    """yaw 오차 → 회전 명령 (비례 감속).

    bang-bang(부호만 보고 고정 max_speed) 은 실기의 지연·관성 때문에 tolerance 밴드를
    오버슈트해 limit cycle(왔다갔다) 을 만든다. 목표에 가까울수록 ``kp * |error|`` 로
    속도를 줄여 밴드로 부드럽게 진입시킨다. 단, min_speed 아래로는 안 떨어뜨려
    정지마찰에 걸려 밴드 직전에서 멈추는 것을 막는다.

    ``error`` 는 wrap_to_pi 된 (target - current) 라고 가정 (부호 = 회전 방향).
    """
    if abs(error) <= tolerance:
        return RotateCmd(reached=True, angular_z=0.0)
    mag = min(max_speed, kp * abs(error))
    if mag < min_speed:
        mag = min_speed
    return RotateCmd(reached=False, angular_z=mag if error > 0 else -mag)


class RotateToYaw(py_trees.behaviour.Behaviour):
    def __init__(
        self,
        name: str,
        target_yaw: float,
        tolerance_rad: float = _DEFAULT_TOLERANCE_RAD,
        angular_speed: float = _DEFAULT_ANGULAR_SPEED,
        kp: float = _DEFAULT_KP,
        min_speed: float = _DEFAULT_MIN_SPEED,
        timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
    ) -> None:
        super().__init__(name)
        self._target_yaw = float(target_yaw)
        self._tolerance = float(tolerance_rad)
        self._angular_speed = float(angular_speed)   # max_speed (멀 때 상한)
        self._kp = float(kp)
        self._min_speed = float(min_speed)
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
        cmd = compute_rotate_cmd(
            error=error,
            tolerance=self._tolerance,
            kp=self._kp,
            min_speed=self._min_speed,
            max_speed=self._angular_speed,
        )
        if cmd.reached:
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

        # 비례 감속 — 목표 근처에서 속도↓ (오버슈트/limit cycle 방지). compute_rotate_cmd 참조.
        self._publish_twist(0.0, cmd.angular_z)
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
