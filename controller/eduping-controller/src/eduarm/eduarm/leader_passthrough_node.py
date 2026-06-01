"""Leader → Follower 직결 passthrough — 고정주기 출력 + EMA + 속도 캡.

leader 와 follower 가 동일 URDF — joint 1:1 매핑. move_group FK/IK 호출 0.

떨림 대책 (핵심):
  - **출력 = 고정주기 타이머** (output_hz). WS 로 들어오는 leader 는 도착 타이밍이
    불규칙(버스트)해서, 받을 때마다 publish 하면 velocity cap 의 dt 가 들쭉날쭉 →
    버스트 땐 안 움직이고 갭 뒤엔 튐 = 떨림. 출력을 도착과 분리해 일정 dt 로 publish.
  - **EMA 저역통과** — 고정 주기로 최신 leader 를 향해 수렴 (센서 노이즈/지터 흡수).
  - **속도 캡** — per-joint 최대 각속도 (안전 핵심). 고정 dt 라 step 이 균일.

장애물 방향성 차단 (obstacle_block):
  - D435 voxel(/eduping/world_voxels, world frame, self-filter 적용) 과 forearm(link4)
    의 최근접 거리 d 를 매 tick 계산.
  - d < block_dist 면 차단 ON. 차단 중엔 **마지막 안전자세(safe_pos) 쪽으로 가는
    관절 성분만 허용**하고, 더 파고드는(멀어지는) 성분은 hold → 전진은 막고 후퇴는
    허용 (데드락 없음). d > release_dist 로 회복되면 차단 OFF (히스테리시스).
  - voxel 없음 / TF 실패 시 fail-open (차단 안 함 — 순간 누락에 헛 freeze 방지).

흐름:
  /eduping/leader/joint_states (불규칙) → on_leader → 최신 target 저장 (publish 안 함)
  /eduping/world_voxels        (15Hz)   → on_voxels → 최신 voxel 저장 (장애물 거리용)
  timer (output_hz, 균일)               → EMA → 속도 캡 → 장애물 차단 → JTC publish
  /joint_states                          → 시작 위치 seed (첫 명령 점프 방지)
  /tf                                    → forearm(link4) world 좌표 lookup

active gate — control-service teleop relay 가 leader 프레임 forward 를 ON/OFF.
woobuntu 는 start_active:=true 로 상시 active.

Params:
  start_active          (bool,  default False)  True 면 부팅부터 active.
  leader_smoothing      (float, default 0.3)    EMA alpha (고정주기). 1.0=무필터, 작을수록 부드럽고 지연↑.
  max_joint_vel         (float, default 1.0)    per-joint 최대 각속도 (rad/s).
  output_hz             (float, default 50.0)   JTC 출력 주기.
  obstacle_block        (bool,  default True)   장애물 방향성 차단 on/off.
  obstacle_block_dist   (float, default 0.06)   forearm-장애물 거리 < 이 값(m) 이면 차단 ON.
  obstacle_release_dist (float, default 0.10)   거리 > 이 값(m) 으로 회복되면 차단 OFF (히스테리시스).
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
from rclpy.time import Time
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32MultiArray
from std_srvs.srv import SetBool
from tf2_ros import Buffer, TransformException, TransformListener
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

# 장애물 거리 감시 링크 — forearm(link4) 만. 손목/그리퍼는 청진기 환자 접촉 위해 자유.
TRACKED_LINK = {side: f"openarm_{side}_link4" for side in SIDES}
WORLD_FRAME = "world"


def directional_gate(
    cmd: list[float], out: list[float], safe: list[float]
) -> list[float]:
    """차단 중 per-joint 방향성 게이트.

    각 관절을 독립적으로: 이번 tick 의 명령 변화(cmd→out)가 마지막 안전자세(safe)
    **쪽으로** 가면(후퇴) 허용, **멀어지면**(더 파고듦) 현재값(cmd) 으로 hold.
    safe 에 이미 도달한 관절(retreat=0)에서의 모든 이동은 멀어지는 것이라 hold.
    이로써 전진은 막고 후퇴(들어온 길 되짚기)는 허용 — 데드락 없음.
    """
    gated: list[float] = []
    for c, o, s in zip(cmd, out, safe):
        move = o - c            # 이번 tick 의도한 변화.
        retreat = s - c         # safe 쪽 방향.
        if move == 0.0:
            gated.append(o)                      # 정지 — 그대로.
        elif retreat == 0.0:
            gated.append(c)                      # 이미 safe — 더 가면 멀어짐, hold.
        elif (move > 0.0) == (retreat > 0.0):
            gated.append(o)                      # 같은 방향 = 후퇴, 허용.
        else:
            gated.append(c)                      # 반대 = 전진, hold.
    return gated


class LeaderPassthrough(Node):
    def __init__(self) -> None:
        super().__init__("leader_passthrough")

        self._cb_group = ReentrantCallbackGroup()

        self.create_subscription(
            JointState, "/eduping/leader/joint_states", self._on_leader, 10,
            callback_group=self._cb_group,
        )
        # 현재 follower — 첫 명령을 follower 자세에서 시작 (시작 점프 방지) 용.
        self.create_subscription(
            JointState, "/joint_states", self._on_follower, 10,
            callback_group=self._cb_group,
        )
        # D435 voxel (world frame, self-filter 적용) — 장애물 거리 계산 입력.
        self.create_subscription(
            Float32MultiArray, "/eduping/world_voxels", self._on_voxels, 1,
            callback_group=self._cb_group,
        )
        self._latest_follower: JointState | None = None
        self._voxels: np.ndarray | None = None   # (N, 3) world frame, 없으면 None.
        self._lock = threading.Lock()

        # TF — forearm 링크 world 좌표 lookup (장애물 거리).
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)

        # on_leader 가 저장하는 최신 target (raw). timer 가 읽어 EMA+cap 후 publish.
        self._target_pos: dict[str, list[float] | None] = {side: None for side in SIDES}
        self._target_grip: dict[str, float | None] = {side: None for side in SIDES}

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
        # 직전 출력 위치 (EMA 상태 + velocity cap 출발점).
        self._cmd_pos: dict[str, list[float] | None] = {side: None for side in SIDES}
        # 장애물 차단 상태 — 마지막 안전자세(safe) + 차단 플래그 (히스테리시스).
        self._safe_pos: dict[str, list[float] | None] = {side: None for side in SIDES}
        self._blocked: dict[str, bool] = {side: False for side in SIDES}

        self.declare_parameter("start_active", False)
        self._active = bool(
            self.get_parameter("start_active").get_parameter_value().bool_value
        )
        a = float(
            self.declare_parameter("leader_smoothing", 0.3)
            .get_parameter_value().double_value
        )
        self._smooth_a = min(1.0, max(0.01, a))
        self._max_vel = float(
            self.declare_parameter("max_joint_vel", 1.0)
            .get_parameter_value().double_value
        )
        self._out_hz = max(
            5.0,
            float(self.declare_parameter("output_hz", 50.0)
                  .get_parameter_value().double_value),
        )
        self._dt = 1.0 / self._out_hz
        # 장애물 방향성 차단.
        self._obstacle_block = bool(
            self.declare_parameter("obstacle_block", True)
            .get_parameter_value().bool_value
        )
        self._block_dist = float(
            self.declare_parameter("obstacle_block_dist", 0.06)
            .get_parameter_value().double_value
        )
        self._release_dist = max(
            self._block_dist,
            float(self.declare_parameter("obstacle_release_dist", 0.10)
                  .get_parameter_value().double_value),
        )
        self._block_warned_at: float = 0.0

        self.create_service(
            SetBool, "~/set_active", self._on_set_active,
            callback_group=self._cb_group,
        )
        # 고정주기 출력 타이머 — 도착 지터와 분리.
        self.create_timer(self._dt, self._tick, callback_group=self._cb_group)

        self.get_logger().info(
            f"leader_passthrough ready (active={self._active}, smoothing={self._smooth_a}, "
            f"max_vel={self._max_vel} rad/s, out={self._out_hz}Hz, "
            f"obstacle_block={self._obstacle_block} "
            f"block<{self._block_dist}m release>{self._release_dist}m)"
        )

    def _on_set_active(self, request: SetBool.Request, response: SetBool.Response):
        active = bool(request.data)
        if not active:
            # 정지 — EMA/cap + 차단 상태 리셋해 다음 시작 때 follower 에서 다시 seed.
            for side in SIDES:
                self._cmd_pos[side] = None
                self._safe_pos[side] = None
                self._blocked[side] = False
        self._active = active
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
        # publish 안 함 — 최신 target 만 저장. 출력은 _tick (고정주기) 이 담당.
        leader_idx = {n: i for i, n in enumerate(msg.name)}
        with self._lock:
            for side in SIDES:
                try:
                    self._target_pos[side] = [
                        msg.position[leader_idx[j]] for j in ARM_JOINTS[side]
                    ]
                except (KeyError, IndexError):
                    continue
                if GRIPPER_JOINT[side] in leader_idx:
                    self._target_grip[side] = msg.position[leader_idx[GRIPPER_JOINT[side]]]

    def _tick(self) -> None:
        if not self._active:
            return
        with self._lock:
            follower = self._latest_follower
            targets = {s: self._target_pos[s] for s in SIDES}
            grips = {s: self._target_grip[s] for s in SIDES}
        follower_idx = (
            {n: i for i, n in enumerate(follower.name)} if follower is not None else {}
        )

        a = self._smooth_a
        max_step = self._max_vel * self._dt
        for side in SIDES:
            target = targets[side]
            if target is None:
                continue

            cmd = self._cmd_pos[side]
            # 시작 — follower 현재 자세에서 출발 (점프 방지). 없으면 target 에서 시작.
            if cmd is None:
                if follower is not None and all(j in follower_idx for j in ARM_JOINTS[side]):
                    cmd = [follower.position[follower_idx[j]] for j in ARM_JOINTS[side]]
                else:
                    cmd = list(target)

            out: list[float] = []
            for c, t in zip(cmd, target):
                # EMA 저역통과 (고정 dt).
                nxt = a * t + (1.0 - a) * c
                # 속도 캡.
                d = nxt - c
                if d > max_step:
                    nxt = c + max_step
                elif d < -max_step:
                    nxt = c - max_step
                out.append(nxt)

            # 장애물 방향성 차단 — 전진 막고 후퇴 허용.
            if self._obstacle_block:
                out = self._apply_obstacle_gate(side, cmd, out)

            self._cmd_pos[side] = out
            self._publish_jtc(side, out)

            grip = grips[side]
            if grip is not None:
                self._send_gripper(side, grip)

    # ── 장애물 방향성 차단 ──────────────────────────────────────────────
    def _apply_obstacle_gate(
        self, side: str, cmd: list[float], out: list[float]
    ) -> list[float]:
        """forearm-장애물 거리로 차단 상태 갱신 후, 차단 중이면 방향성 게이트 적용."""
        with self._lock:
            voxels = self._voxels
        d = self._min_link_dist(side, voxels)
        if d is None:
            return out  # TF 실패 — fail-open (상태 유지, 차단 안 함).

        # 히스테리시스 — block_dist 에서 ON, release_dist 에서 OFF.
        if self._blocked[side]:
            if d > self._release_dist:
                self._blocked[side] = False
        elif d < self._block_dist:
            self._blocked[side] = True
            if self._safe_pos[side] is None:
                self._safe_pos[side] = list(cmd)

        if not self._blocked[side]:
            self._safe_pos[side] = list(out)   # 여유 — 마지막 안전 명령 기억.
            return out

        now = time.monotonic()
        if now - self._block_warned_at > 1.0:
            self.get_logger().info(
                f"obstacle block [{side}] — d={d:.3f}m (<{self._block_dist}m), 후퇴만 허용"
            )
            self._block_warned_at = now
        safe = self._safe_pos[side] or list(cmd)
        return directional_gate(cmd, out, safe)

    def _min_link_dist(self, side: str, voxels: np.ndarray | None) -> float | None:
        """forearm 링크와 최근접 voxel 거리(m). 장애물 없으면 inf, TF 실패면 None."""
        if voxels is None or voxels.shape[0] == 0:
            return float("inf")
        p = self._lookup_link_position(TRACKED_LINK[side])
        if p is None:
            return None
        diffs = voxels - p[None, :]
        return float(np.sqrt((diffs * diffs).sum(axis=1).min()))

    def _lookup_link_position(self, link: str) -> np.ndarray | None:
        try:
            t = self._tf_buffer.lookup_transform(WORLD_FRAME, link, Time())
        except TransformException:
            return None
        p = t.transform.translation
        return np.array([p.x, p.y, p.z], dtype=np.float32)

    def _publish_jtc(self, side: str, positions: list[float]) -> None:
        jt = JointTrajectory()
        jt.joint_names = ARM_JOINTS[side]
        pt = JointTrajectoryPoint()
        pt.positions = [float(p) for p in positions]
        # 한 tick hold — 다음 tick 에 새 goal 이 덮어씀.
        pt.time_from_start = DurMsg(sec=0, nanosec=int(self._dt * 1e9))
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
