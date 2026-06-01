"""Leader → Follower 직결 passthrough + EMA 스무딩 + 속도 캡.

leader 와 follower 가 동일 URDF — joint 1:1 매핑. move_group FK/IK 호출 0.

vision(D435 voxel) 기반 거리 속도 제어는 **제거** — teleop 떨림 원인이라 단순화.
안전은 MAX_JOINT_VEL 속도 캡만으로 담보 (per-joint 최대 각속도 제한).

흐름:
  /eduping/leader/joint_states (30~50Hz) → on_leader → EMA 저역통과 → 속도 캡 → JTC
  /joint_states                          → 시작 위치 seed (첫 명령 점프 방지)

publish: JTC (joint_trajectory_controller). gripper 는 액션.

active gate — control-service teleop relay 가 leader 프레임 forward 를 ON/OFF.
woobuntu 는 start_active:=true 로 상시 active (게이트는 relay 가 담당).

Params:
  start_active     (bool,  default False)  True 면 부팅부터 active.
  leader_smoothing (float, default 0.4)    EMA alpha. 1.0=무필터, 작을수록 부드럽고 지연↑.
  max_joint_vel    (float, default 1.0)    per-joint 최대 각속도 (rad/s).
"""
from __future__ import annotations

import math
import threading
import time

import rclpy
from builtin_interfaces.msg import Duration as DurMsg
from control_msgs.action import GripperCommand
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
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

JTC_HOLD_S = 0.05               # 다음 leader frame 들어오기 전까지 hold.
GRIPPER_DELTA_THRESHOLD = 0.001
GRIPPER_MAX_EFFORT = 10.0


class LeaderPassthrough(Node):
    def __init__(self) -> None:
        super().__init__("leader_passthrough")

        self._cb_group = ReentrantCallbackGroup()

        self.create_subscription(
            JointState, "/eduping/leader/joint_states", self._on_leader, 10,
            callback_group=self._cb_group,
        )
        # 현재 follower 위치 — 첫 명령을 follower 현재 자세에서 시작 (시작 점프 방지) 용.
        self.create_subscription(
            JointState, "/joint_states", self._on_follower, 10,
            callback_group=self._cb_group,
        )
        self._latest_follower: JointState | None = None
        self._lock = threading.Lock()

        self._jtc_pub = {
            side: self.create_publisher(JointTrajectory, JTC_TOPIC[side], 10)
            for side in SIDES
        }
        self._gripper_clients = {
            side: ActionClient(
                self, GripperCommand, GRIPPER_ACTION[side],
                callback_group=self._cb_group,
            )
            for side in SIDES
        }
        self._last_gripper_cmd = {side: math.nan for side in SIDES}
        # 직전 publish 한 joint 위치 + 시각 — velocity cap 용.
        self._last_pub_pos: dict[str, list[float] | None] = {side: None for side in SIDES}
        self._last_pub_ts: dict[str, float] = {side: 0.0 for side in SIDES}

        # start_active=True (woobuntu 2-머신): 게이트는 control-service relay 담당 →
        # 항상 active. False (mock/단일머신): ~/set_active 서비스로 게이트.
        self.declare_parameter("start_active", False)
        self._active = bool(
            self.get_parameter("start_active").get_parameter_value().bool_value
        )
        # 떨림 완화 — leader 위치 EMA 저역통과. alpha=1.0 무필터, 작을수록 부드럽고 지연↑.
        a = float(
            self.declare_parameter("leader_smoothing", 0.4)
            .get_parameter_value().double_value
        )
        self._smooth_a = min(1.0, max(0.01, a))
        self._leader_smooth: dict[str, list[float] | None] = {side: None for side in SIDES}
        # 속도 캡 — per-joint 최대 각속도 (rad/s). 안전 핵심.
        self._max_vel = float(
            self.declare_parameter("max_joint_vel", 1.0)
            .get_parameter_value().double_value
        )

        self.create_service(
            SetBool, "~/set_active", self._on_set_active,
            callback_group=self._cb_group,
        )

        self.get_logger().info(
            f"leader_passthrough ready (active={self._active}, smoothing={self._smooth_a}, "
            f"max_vel={self._max_vel} rad/s)"
        )

    def _on_set_active(self, request: SetBool.Request, response: SetBool.Response):
        self._active = bool(request.data)
        response.success = True
        response.message = f"active={self._active}"
        self.get_logger().info(f"leader_passthrough {response.message}")
        return response

    def _on_follower(self, msg: JointState) -> None:
        with self._lock:
            self._latest_follower = msg

    def _on_leader(self, msg: JointState) -> None:
        if not self._active:
            return
        with self._lock:
            follower = self._latest_follower

        follower_idx = (
            {n: i for i, n in enumerate(follower.name)} if follower is not None else {}
        )
        leader_idx = {n: i for i, n in enumerate(msg.name)}
        for side in SIDES:
            try:
                leader_pos = [msg.position[leader_idx[j]] for j in ARM_JOINTS[side]]
            except (KeyError, IndexError):
                continue

            # EMA 저역통과 — 떨림(WS 지터 + 센서 노이즈) 완화. alpha=1 이면 무필터.
            a = self._smooth_a
            prev = self._leader_smooth[side]
            if prev is None or a >= 1.0:
                leader_pos = list(leader_pos)
            else:
                leader_pos = [a * cur + (1.0 - a) * p for cur, p in zip(leader_pos, prev)]
            self._leader_smooth[side] = leader_pos

            # 첫 명령은 follower 현재 자세에서 시작 (시작 점프 방지) — velocity cap seed.
            if self._last_pub_pos[side] is None and follower is not None and all(
                j in follower_idx for j in ARM_JOINTS[side]
            ):
                self._last_pub_pos[side] = [
                    follower.position[follower_idx[j]] for j in ARM_JOINTS[side]
                ]
                self._last_pub_ts[side] = time.monotonic()

            self._publish_jtc(side, leader_pos)

            if GRIPPER_JOINT[side] in leader_idx:
                grip = msg.position[leader_idx[GRIPPER_JOINT[side]]]
                self._send_gripper(side, grip)

    def _publish_jtc(self, side: str, positions: list[float]) -> None:
        # velocity cap — per-joint |delta| ≤ max_joint_vel × dt.
        now = time.monotonic()
        last = self._last_pub_pos[side]
        if last is not None:
            dt = max(1e-3, now - self._last_pub_ts[side])
            max_step = self._max_vel * dt
            capped: list[float] = []
            for prev, target in zip(last, positions):
                d = target - prev
                if d > max_step:
                    capped.append(prev + max_step)
                elif d < -max_step:
                    capped.append(prev - max_step)
                else:
                    capped.append(target)
            positions = capped
        self._last_pub_pos[side] = list(positions)
        self._last_pub_ts[side] = now

        jt = JointTrajectory()
        jt.joint_names = ARM_JOINTS[side]
        pt = JointTrajectoryPoint()
        pt.positions = [float(p) for p in positions]
        pt.time_from_start = DurMsg(sec=0, nanosec=int(JTC_HOLD_S * 1e9))
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
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
