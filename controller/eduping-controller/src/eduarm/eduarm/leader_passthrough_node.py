"""Leader → Follower 직결 passthrough + octomap collision gate.

leader 와 follower 가 동일 URDF (양쪽 다 openarm v10) 라 joint 1:1 매핑이 자연스러움.
move_group 의 FK/IK 호출 0. 대신 `/check_state_validity` 를 10Hz 백그라운드 호출해
follower 의 다음 명령 (= leader 현재 값) 이 octomap voxel 과 충돌 안 하는지 확인.

흐름:
    /eduping/leader/joint_states  (FeetechLeader 30~50Hz)
        │
        ├─→ on_leader callback: valid flag 가 fresh (< 200ms) 면 → JTC publish.
        │                       fresh 가 아니면 skip (마지막 안전 자세 hold).
        │
        └─→ _validity_timer (10Hz): RobotState 합성 → /check_state_validity 호출.
                                    valid 면 _last_valid_at 갱신.

active gate — UI 의 "Telehealth 시작" 버튼 (`~/set_active` SetBool) 이 켜기 전엔
publish 안 함. False 면 JTC 가 마지막 명령 hold.

충돌 감지 latency ≤ VALIDITY_FRESH_S (200ms). 그 시간 안에 follower 가 voxel 침범
가능 — mock_components 시뮬에선 무해. 실물 HW 면 더 짧게 조절 필요.
"""
from __future__ import annotations

import math
import threading
import time

import rclpy
from builtin_interfaces.msg import Duration as DurMsg
from control_msgs.action import GripperCommand
from moveit_msgs.msg import RobotState
from moveit_msgs.srv import GetStateValidity
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
# IK 가 사용하던 full robot joint 순서 (양팔 + gripper) — RobotState 합성용.
ALL_ROBOT_JOINTS = [
    "openarm_left_finger_joint1",
    *ARM_JOINTS["left"],
    "openarm_right_finger_joint1",
    *ARM_JOINTS["right"],
]

JTC_HOLD_S = 0.05               # 다음 leader frame 들어오기 전까지 hold.
GRIPPER_DELTA_THRESHOLD = 0.001
GRIPPER_MAX_EFFORT = 10.0

VALIDITY_PERIOD_S = 0.1         # 10Hz check.
VALIDITY_FRESH_S = 0.25         # 최근 valid 결과가 250ms 이내일 때만 publish 통과.
VALIDITY_SERVICE_TIMEOUT_S = 0.3


class LeaderPassthrough(Node):
    def __init__(self) -> None:
        super().__init__("leader_passthrough")

        self._cb_group = ReentrantCallbackGroup()

        self.create_subscription(
            JointState, "/eduping/leader/joint_states", self._on_leader, 10,
            callback_group=self._cb_group,
        )

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

        # Collision gate — /check_state_validity 의 fresh 결과만 publish 허용.
        self._validity_client = self.create_client(
            GetStateValidity, "/check_state_validity",
            callback_group=self._cb_group,
        )
        self._last_valid_at: float = 0.0
        self._latest_leader: JointState | None = None
        self._lock = threading.Lock()
        self._blocked_warned_at: float = 0.0
        self.create_timer(
            VALIDITY_PERIOD_S, self._validity_tick,
            callback_group=self._cb_group,
        )

        self._active = False
        self.create_service(
            SetBool, "~/set_active", self._on_set_active,
            callback_group=self._cb_group,
        )

        self.get_logger().info(
            "leader_passthrough ready (idle — call ~/set_active {data:true} to start)"
        )

    def _on_set_active(self, request: SetBool.Request, response: SetBool.Response):
        self._active = bool(request.data)
        response.success = True
        response.message = f"active={self._active}"
        self.get_logger().info(f"leader_passthrough {response.message}")
        return response

    def _on_leader(self, msg: JointState) -> None:
        with self._lock:
            self._latest_leader = msg
        if not self._active:
            return
        # collision gate — fresh valid 결과 없으면 skip.
        if time.monotonic() - self._last_valid_at > VALIDITY_FRESH_S:
            now = time.monotonic()
            if now - self._blocked_warned_at > 1.0:
                self.get_logger().warn(
                    "publish blocked — no fresh validity (collision suspected)"
                )
                self._blocked_warned_at = now
            return

        idx = {n: i for i, n in enumerate(msg.name)}
        for side in SIDES:
            try:
                positions = [msg.position[idx[j]] for j in ARM_JOINTS[side]]
            except (KeyError, IndexError):
                continue
            self._publish_jtc(side, positions)

            if GRIPPER_JOINT[side] in idx:
                grip = msg.position[idx[GRIPPER_JOINT[side]]]
                self._send_gripper(side, grip)

    # ── collision gate ──────────────────────────────────────────────────
    def _validity_tick(self) -> None:
        if not self._active:
            return
        with self._lock:
            leader = self._latest_leader
        if leader is None:
            return
        if not self._validity_client.service_is_ready():
            return
        # leader joint 값으로 follower RobotState 합성 (16 joint full state).
        idx = {n: i for i, n in enumerate(leader.name)}
        positions: list[float] = []
        ok = True
        for jn in ALL_ROBOT_JOINTS:
            if jn in idx:
                positions.append(leader.position[idx[jn]])
            else:
                positions.append(0.0)
                ok = False
        if not ok:
            return

        req = GetStateValidity.Request()
        rs = RobotState()
        rs.is_diff = False
        js = JointState()
        js.name = list(ALL_ROBOT_JOINTS)
        js.position = positions
        rs.joint_state = js
        req.robot_state = rs
        # group_name 비워두면 전체 robot 체크 (양팔 + grippers).
        req.group_name = ""

        future = self._validity_client.call_async(req)
        end = time.monotonic() + VALIDITY_SERVICE_TIMEOUT_S
        while not future.done() and time.monotonic() < end:
            time.sleep(0.005)
        if not future.done():
            return
        res = future.result()
        if not res:
            return
        if res.valid:
            self._last_valid_at = time.monotonic()

    def _publish_jtc(self, side: str, positions: list[float]) -> None:
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
    # ReentrantCallbackGroup + _validity_tick 안에서 future polling → MultiThreaded 필요.
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
