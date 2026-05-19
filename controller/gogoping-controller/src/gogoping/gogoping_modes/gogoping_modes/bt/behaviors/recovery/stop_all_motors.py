"""StopAllMotors — ERROR state 진입 시 cmd_vel=0 + motor torque OFF.

긴급 안전 정지. 사용자 또는 안전 monitor 가 fault trigger 발화 → FSM ERROR 진입 →
BT_error_main 빌드 → 본 behavior 의 initialise() 에서 즉시 정지.

- ``initialise()`` (1회): ``ctx.cmd_vel_pub.publish(Twist(0,0))`` + ``ctx.base_driver.release_torque()``
  - cmd_vel=0: 진행 중인 nav 명령이 모터에 전달되더라도 정지
  - release_torque: ZLAC disable — 사람이 robot 을 안전한 곳으로 밀어내기 가능
- ``update()``: ``Status.SUCCESS`` — 1 tick 으로 끝 (Sequence 안에서 다음 단계로 진행)
- ``terminate()``: 무동작. ERROR 가 terminal 이라 호출될 일 사실상 없음

ERROR 가 terminal state 라 enable 복원은 robot 재시작 시 ``bringup.py`` 의 init sequence
가 자동 처리.

| 파일 | bt/behaviors/recovery/stop_all_motors.py |
| Used in | BT_error_main |
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Status

from geometry_msgs.msg import Twist

if TYPE_CHECKING:
    from ....context import Context


class StopAllMotors(py_trees.behaviour.Behaviour):
    """cmd_vel=0 + torque OFF — ERROR state 진입 즉시 1회."""

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context

    def initialise(self) -> None:
        # 1) cmd_vel = 0 — 현재 시점 publish 중인 nav 명령 즉시 cancel
        pub = getattr(self.ctx, "cmd_vel_pub", None)
        if pub is not None:
            try:
                msg = Twist()
                msg.linear.x = 0.0
                msg.angular.z = 0.0
                pub.publish(msg)
            except Exception as e:
                self.logger.warning(f"StopAllMotors: cmd_vel publish 실패 — {e}")
        # 2) base_driver torque OFF — fire-and-forget (BaseDriverClient 가 비동기 처리)
        driver = getattr(self.ctx, "base_driver", None)
        if driver is not None:
            try:
                driver.release_torque()
            except Exception as e:
                self.logger.warning(f"StopAllMotors: release_torque 실패 — {e}")
        self.logger.info("StopAllMotors: emergency stop — cmd_vel=0 + torque OFF")

    def update(self) -> Status:
        return Status.SUCCESS

    def terminate(self, new_status: Status) -> None:
        # no-op — ERROR terminal 이라 종료 시점 없음
        pass
