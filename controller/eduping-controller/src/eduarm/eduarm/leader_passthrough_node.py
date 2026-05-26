"""Leader → Follower 직결 passthrough + 거리 기반 velocity scaling.

leader 와 follower 가 동일 URDF — joint 1:1 매핑. move_group FK/IK 호출 0.

D435 octomap voxel 까지 거리 d 기반 v_scale:
  d ≥ D_SLOW  → 1.0
  d ≤ D_STOP  → V_FLOOR (최소 속도, 0 아님 — 멀어질 때 자연스럽게 따라감)
  사이        → 선형 보간

publish: scaled_target = current_follower + (leader - current_follower) × v_scale

흐름:
  /eduping/leader/joint_states (30~50Hz) → on_leader
  /eduping/world_voxels        (15Hz)   → voxel numpy array
  /joint_states                          → current follower
  /tf                                    → follower 링크 world 좌표

active gate — UI 의 "Telehealth 시작" 버튼 (`~/set_active` SetBool).
"""
from __future__ import annotations

import math
import threading
import time

import numpy as np
import rclpy
from builtin_interfaces.msg import Duration as DurMsg
from control_msgs.action import GripperCommand
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32MultiArray
from std_srvs.srv import SetBool
from tf2_ros import Buffer, TransformListener, TransformException
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

# Telehealth 최대 joint 속도 — 안전 우선 (~57°/s, 사람 팔 속도). 7 joint 공통.
MAX_JOINT_VEL = 1.0             # rad/s

# Collision-aware velocity scaling.
D_STOP = 0.05      # 이 거리 이내면 V_FLOOR 적용.
D_SLOW = 0.25      # 이 거리부터 감속 시작.
V_FLOOR = 0.05     # 최소 속도 — leader 따라가는 능력 유지 (멀어질 때 자연 복귀).
TRACKED_LINKS = {
    "left":  ["openarm_left_link4", "openarm_left_link6", "openarm_left_hand_tcp"],
    "right": ["openarm_right_link4", "openarm_right_link6", "openarm_right_hand_tcp"],
}
WORLD_FRAME = "world"


class LeaderPassthrough(Node):
    def __init__(self) -> None:
        super().__init__("leader_passthrough")

        self._cb_group = ReentrantCallbackGroup()

        self.create_subscription(
            JointState, "/eduping/leader/joint_states", self._on_leader, 10,
            callback_group=self._cb_group,
        )
        # 현재 follower 위치 — collision blending 의 출발점.
        self.create_subscription(
            JointState, "/joint_states", self._on_follower, 10,
            callback_group=self._cb_group,
        )
        # D435 voxel 좌표 (world frame, m) — collision 거리 계산 입력.
        self.create_subscription(
            Float32MultiArray, "/eduping/world_voxels", self._on_voxels, 1,
            callback_group=self._cb_group,
        )
        self._latest_follower: JointState | None = None
        self._voxels: np.ndarray | None = None   # (N, 3) world frame.
        self._lock = threading.Lock()

        # TF 로 follower 링크 좌표 lookup.
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)

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

        self._slow_warned_at: float = 0.0
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

    def _on_follower(self, msg: JointState) -> None:
        with self._lock:
            self._latest_follower = msg

    def _on_voxels(self, msg: Float32MultiArray) -> None:
        data = msg.data
        if not data:
            with self._lock:
                self._voxels = None
            return
        try:
            arr = np.asarray(data, dtype=np.float32).reshape(-1, 3)
        except ValueError:
            return
        with self._lock:
            self._voxels = arr

    def _on_leader(self, msg: JointState) -> None:
        if not self._active:
            return
        with self._lock:
            follower = self._latest_follower
            voxels = self._voxels

        # 1) v_scale 계산 — follower 링크와 voxel 의 최소 거리 기반.
        v_scale = self._compute_v_scale(voxels)

        # 2) follower current 가 없으면 v_scale=1 (= 옛 passthrough 와 동일).
        follower_idx = (
            {n: i for i, n in enumerate(follower.name)} if follower is not None else {}
        )

        leader_idx = {n: i for i, n in enumerate(msg.name)}
        for side in SIDES:
            try:
                leader_pos = [msg.position[leader_idx[j]] for j in ARM_JOINTS[side]]
            except (KeyError, IndexError):
                continue

            # current follower joints — 없으면 leader 그대로 사용.
            if follower is not None and all(j in follower_idx for j in ARM_JOINTS[side]):
                cur_pos = [follower.position[follower_idx[j]] for j in ARM_JOINTS[side]]
                blended = [
                    cur + (lead - cur) * v_scale for cur, lead in zip(cur_pos, leader_pos)
                ]
            else:
                blended = leader_pos
            self._publish_jtc(side, blended)

            if GRIPPER_JOINT[side] in leader_idx:
                grip = msg.position[leader_idx[GRIPPER_JOINT[side]]]
                self._send_gripper(side, grip)

    # ── velocity scaling ────────────────────────────────────────────────
    def _compute_v_scale(self, voxels: np.ndarray | None) -> float:
        """V_FLOOR ~ 1.0. 거리 기반 선형 스케일.

        d ≥ D_SLOW  → 1.0
        d ≤ D_STOP  → V_FLOOR
        사이        → 선형
        """
        if voxels is None or voxels.shape[0] == 0:
            return 1.0

        min_d = float("inf")
        for side in SIDES:
            for link in TRACKED_LINKS[side]:
                p = self._lookup_link_position(link)
                if p is None:
                    continue
                diffs = voxels - p[None, :]
                d = float(np.sqrt((diffs * diffs).sum(axis=1).min()))
                if d < min_d:
                    min_d = d
        if min_d == float("inf"):
            return 1.0

        # 선형 보간 후 V_FLOOR 절대 하한 보장 — 뚫고 들어가 d < D_STOP 이 되거나
        # 음수가 되는 edge case 에서도 최소 속도 유지.
        if min_d >= D_SLOW:
            interp = 1.0
        else:
            interp = V_FLOOR + (1.0 - V_FLOOR) * (min_d - D_STOP) / (D_SLOW - D_STOP)
        scale = max(V_FLOOR, min(1.0, interp))

        now = time.monotonic()
        if scale < 0.99 and now - self._slow_warned_at > 1.0:
            self.get_logger().info(f"slowdown — min_d={min_d:.3f}m v_scale={scale:.2f}")
            self._slow_warned_at = now
        return scale

    def _lookup_link_position(self, link: str) -> np.ndarray | None:
        try:
            t = self._tf_buffer.lookup_transform(
                WORLD_FRAME, link, rclpy.time.Time(),
            )
        except TransformException:
            return None
        p = t.transform.translation
        return np.array([p.x, p.y, p.z], dtype=np.float32)

    def _publish_jtc(self, side: str, positions: list[float]) -> None:
        # velocity cap — per-joint |delta| ≤ MAX_JOINT_VEL × dt.
        now = time.monotonic()
        last = self._last_pub_pos[side]
        if last is not None:
            dt = max(1e-3, now - self._last_pub_ts[side])
            max_step = MAX_JOINT_VEL * dt
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
