#!/usr/bin/env python3
"""Bringup 직후 양팔 JTC 에 'hold current pose' 보간 goal 을 보내 시작 jerk 완화.

joint_trajectory_controller 가 활성화되는 순간 controller 의 hold target 이 무엇으로
잡혀있는지에 따라 모터가 살짝 튀는 경우가 있다. `/joint_states` 의 현재 양팔 pose 를
읽어 같은 위치까지 `ramp_s` 동안 보간하는 trajectory goal 을 명시적으로 보내면, 활성화
직후의 모션을 통제된 spline 으로 묶을 수 있다.

(하드웨어 단의 모터 토크 전이로 인한 첫 ~50ms 의 마이크로 점프까지는 막지 못함 —
그건 HW interface gain ramp 가 필요.)

launch 의 TimerAction (delay) 으로 controller spawn 이후 한 번만 실행되고 종료.
"""
from __future__ import annotations

import time

import rclpy
from builtin_interfaces.msg import Duration
from control_msgs.action import FollowJointTrajectory
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectoryPoint


RIGHT_NAMES = [f"openarm_right_joint{i}" for i in range(1, 8)]
LEFT_NAMES = [f"openarm_left_joint{i}" for i in range(1, 8)]
DEFAULT_RAMP_S = 2.0
DEFAULT_TIMEOUT_S = 10.0


class SoftStart(Node):
    def __init__(self) -> None:
        super().__init__("eduping_soft_start")
        self.declare_parameter("ramp_s", DEFAULT_RAMP_S)
        self.declare_parameter("timeout_s", DEFAULT_TIMEOUT_S)
        self._ramp_s = float(self.get_parameter("ramp_s").value)
        self._timeout_s = float(self.get_parameter("timeout_s").value)
        self._last_js: JointState | None = None
        self.create_subscription(JointState, "/joint_states", self._on_js, 10)
        self._ac_right = ActionClient(
            self,
            FollowJointTrajectory,
            "/right_joint_trajectory_controller/follow_joint_trajectory",
        )
        self._ac_left = ActionClient(
            self,
            FollowJointTrajectory,
            "/left_joint_trajectory_controller/follow_joint_trajectory",
        )

    def _on_js(self, msg: JointState) -> None:
        self._last_js = msg

    def _wait_for_js(self) -> bool:
        deadline = time.monotonic() + self._timeout_s
        self.get_logger().info("waiting for /joint_states ...")
        while rclpy.ok() and self._last_js is None and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
        return self._last_js is not None

    def _extract(self, names: list[str]) -> list[float] | None:
        js = self._last_js
        if js is None:
            return None
        try:
            return [float(js.position[js.name.index(n)]) for n in names]
        except (ValueError, IndexError):
            return None

    def _send_hold(self, side: str, names: list[str], ac: ActionClient) -> None:
        pos = self._extract(names)
        if pos is None:
            self.get_logger().warn(
                f"{side}: /joint_states 에 {names[0]}.. 누락 — soft start skip"
            )
            return
        if not ac.wait_for_server(timeout_sec=self._timeout_s):
            self.get_logger().warn(f"{side}: trajectory action server 미가동 — skip")
            return
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = list(names)
        pt = JointTrajectoryPoint()
        pt.positions = pos
        sec = int(self._ramp_s)
        nsec = int((self._ramp_s - sec) * 1e9)
        pt.time_from_start = Duration(sec=sec, nanosec=nsec)
        goal.trajectory.points.append(pt)
        ac.send_goal_async(goal)
        self.get_logger().info(
            f"{side}: hold-pose goal sent (ramp={self._ramp_s:.2f}s, "
            f"pose={[round(p, 3) for p in pos]})"
        )

    def run(self) -> None:
        if not self._wait_for_js():
            self.get_logger().warn(
                "/joint_states 가 안 옴 — controller_manager 가 떠 있는지 확인. abort."
            )
            return
        self._send_hold("right", RIGHT_NAMES, self._ac_right)
        self._send_hold("left", LEFT_NAMES, self._ac_left)
        # goal 전송 후 짧게 spin — async future 가 실제 전송되는 시간 확보.
        deadline = time.monotonic() + 1.0
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.05)


def main() -> None:
    rclpy.init()
    node = SoftStart()
    try:
        node.run()
    except Exception as exc:  # noqa: BLE001
        node.get_logger().error(f"soft-start failed: {exc}")
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
