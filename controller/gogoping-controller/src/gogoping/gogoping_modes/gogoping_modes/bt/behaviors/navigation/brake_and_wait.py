"""BrakeAndWait — cmd_vel=0 publish + N초 대기 후 SUCCESS.

nav 도착 직후 robot 의 잔여 관성을 줄이고 카메라 sweep 같은 다음 behavior 전에
완전히 멈추도록 보장. nav2 의 SUCCESS 가 떨어진 시점과 실제 cmd_vel 가 0 으로
멈춘 시점 사이의 미세한 지연 / 잔여 가속을 흡수.

- ``initialise()``: 시작 시각 기록 + cmd_vel=0 즉시 publish (안전 boost)
- ``update()``: 매 tick cmd_vel=0 publish 유지. ``duration_sec`` 경과 시 SUCCESS
- ``terminate(INVALID)``: no-op — 이미 cmd_vel=0 상태로 마지막 publish 된 상태라 cancel 시에도 안전

torque 는 안 건드림 (StopAllMotors 와 다름). ERROR 가 아니라 정상 흐름의 일시 정지.

| 파일 | bt/behaviors/navigation/brake_and_wait.py |
| Used in | BT_patrol_sub (각 visit Sequence 의 NavigateToVertex 와 PanCameraSweep 사이) |
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

import py_trees
from py_trees.common import Status

from geometry_msgs.msg import Twist

if TYPE_CHECKING:
    from ....context import Context


DEFAULT_DURATION_SEC = 0.5


class BrakeAndWait(py_trees.behaviour.Behaviour):
    """cmd_vel=0 publish + ``duration_sec`` 동안 RUNNING 후 SUCCESS."""

    def __init__(
        self,
        name: str,
        context: "Context",
        *,
        duration_sec: float = DEFAULT_DURATION_SEC,
        now_fn: Callable[[], float] = time.monotonic,
    ):
        super().__init__(name)
        self.ctx = context
        self.duration_sec = duration_sec
        self._now = now_fn
        self._t0 = 0.0

    def _publish_zero(self) -> None:
        pub = getattr(self.ctx, "cmd_vel_pub", None)
        if pub is None:
            return
        try:
            msg = Twist()
            msg.linear.x = 0.0
            msg.angular.z = 0.0
            pub.publish(msg)
        except Exception as e:
            self.logger.warning(f"{self.name}: cmd_vel publish 실패 — {e}")

    def initialise(self) -> None:
        self._t0 = self._now()
        self._publish_zero()

    def update(self) -> Status:
        self._publish_zero()
        if self._now() - self._t0 >= self.duration_sec:
            return Status.SUCCESS
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        pass
