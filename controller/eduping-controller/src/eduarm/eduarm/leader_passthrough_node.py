"""Leader → Follower 단순 직결 passthrough (JTC).

아주 단순한 teleop — leader 관절을 받는 즉시 JTC goal 로 publish. 1:1 매핑.
필터 / 고정주기 타이머 / 충돌 감속 없음 (단순화). 안전용 **최대 속도 제한만** 유지.

부드러움은 **JTC 보간창 (interp_s)** 하나로만 조절:
  - leader frame 이 들어올 때마다 "현재→leader" 를 interp_s 에 걸쳐 가도록 goal 을 던짐.
  - JTC(100Hz) 가 그 사이를 보간 → interp_s 가 클수록 부드럽지만 지연↑.

속도 제한 (안전): per-joint |Δ| ≤ max_joint_vel × dt 로 캡. 정상 teleop 모션은 캡
아래라 그대로 통과 — 큰 점프(시작/글리치)만 제한하므로 떨림과 무관.

active gate — control-service teleop relay 가 leader 프레임 forward 를 ON/OFF.
woobuntu 는 start_active:=true 로 상시 active.

Params:
  start_active  (bool,  default False)  True 면 부팅부터 active.
  interp_s      (float, default 0.12)   JTC time_from_start(보간창, s). ↑ 부드럽고 지연↑.
  max_joint_vel (float, default 1.0)    per-joint 최대 각속도(rad/s) — 안전 캡.
"""
from __future__ import annotations

import math
import time

import rclpy
from builtin_interfaces.msg import Duration as DurMsg
from control_msgs.action import GripperCommand
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_srvs.srv import SetBool
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint


SIDES = ("left", "right")
ARM_JOINTS = {
    side: [f"openarm_{side}_joint{i}" for i in range(1, 8)] for side in SIDES
}
GRIPPER_JOINT = {side: f"openarm_{side}_finger_joint1" for side in SIDES}
JTC_TOPIC = {
    side: f"/{side}_joint_trajectory_controller/joint_trajectory" for side in SIDES
}
GRIPPER_ACTION = {
    side: f"/{side}_gripper_controller/gripper_cmd" for side in SIDES
}

GRIPPER_DELTA_THRESHOLD = 0.001
GRIPPER_MAX_EFFORT = 10.0


class LeaderPassthrough(Node):
    def __init__(self) -> None:
        super().__init__("leader_passthrough")

        self.declare_parameter("start_active", False)
        self._active = bool(
            self.get_parameter("start_active").get_parameter_value().bool_value
        )
        self._interp_s = max(
            0.02,
            float(self.declare_parameter("interp_s", 0.12)
                  .get_parameter_value().double_value),
        )
        self._max_vel = float(
            self.declare_parameter("max_joint_vel", 1.0)
            .get_parameter_value().double_value
        )

        self.create_subscription(
            JointState, "/eduping/leader/joint_states", self._on_leader, 10
        )
        self._jtc_pub = {
            side: self.create_publisher(JointTrajectory, JTC_TOPIC[side], 10)
            for side in SIDES
        }
        self._gripper_clients = {
            side: ActionClient(self, GripperCommand, GRIPPER_ACTION[side])
            for side in SIDES
        }
        self._last_gripper_cmd = {side: math.nan for side in SIDES}
        # 속도 캡용 — 직전 publish 위치/시각.
        self._last_pos: dict[str, list[float] | None] = {side: None for side in SIDES}
        self._last_ts: dict[str, float] = {side: 0.0 for side in SIDES}

        self.create_service(SetBool, "~/set_active", self._on_set_active)

        self.get_logger().info(
            f"leader_passthrough ready (active={self._active}, "
            f"interp_s={self._interp_s}, max_vel={self._max_vel} rad/s)"
        )

    def _on_set_active(self, request: SetBool.Request, response: SetBool.Response):
        self._active = bool(request.data)
        response.success = True
        response.message = f"active={self._active}"
        self.get_logger().info(f"leader_passthrough {response.message}")
        return response

    def _on_leader(self, msg: JointState) -> None:
        if not self._active:
            return
        leader_idx = {n: i for i, n in enumerate(msg.name)}
        for side in SIDES:
            try:
                pos = [msg.position[leader_idx[j]] for j in ARM_JOINTS[side]]
            except (KeyError, IndexError):
                continue
            self._publish_jtc(side, pos)
            if GRIPPER_JOINT[side] in leader_idx:
                self._send_gripper(side, msg.position[leader_idx[GRIPPER_JOINT[side]]])

    def _publish_jtc(self, side: str, positions: list[float]) -> None:
        # 속도 캡 (안전) — per-joint |Δ| ≤ max_vel × dt. 정상 모션은 캡 아래라 무영향.
        now = time.monotonic()
        last = self._last_pos[side]
        if last is not None and len(last) == len(positions):
            dt = min(0.1, max(1e-3, now - self._last_ts[side]))
            max_step = self._max_vel * dt
            capped: list[float] = []
            for prev, tgt in zip(last, positions):
                d = tgt - prev
                if d > max_step:
                    capped.append(prev + max_step)
                elif d < -max_step:
                    capped.append(prev - max_step)
                else:
                    capped.append(tgt)
            positions = capped
        self._last_pos[side] = list(positions)
        self._last_ts[side] = now

        jt = JointTrajectory()
        jt.joint_names = ARM_JOINTS[side]
        pt = JointTrajectoryPoint()
        pt.positions = [float(p) for p in positions]
        pt.time_from_start = DurMsg(
            sec=int(self._interp_s),
            nanosec=int((self._interp_s % 1.0) * 1e9),
        )
        jt.points = [pt]
        self._jtc_pub[side].publish(jt)

    def _send_gripper(self, side: str, target: float) -> None:
        last = self._last_gripper_cmd[side]
        if not math.isnan(last) and abs(target - last) < GRIPPER_DELTA_THRESHOLD:
            return
        client = self._gripper_clients[side]
        if not client.server_is_ready():
            return
        goal = GripperCommand.Goal()
        goal.command.position = float(target)
        goal.command.max_effort = GRIPPER_MAX_EFFORT
        client.send_goal_async(goal)
        self._last_gripper_cmd[side] = target


def main() -> None:
    rclpy.init()
    node = LeaderPassthrough()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
