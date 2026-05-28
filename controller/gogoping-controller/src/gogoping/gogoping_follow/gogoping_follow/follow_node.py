"""gogoping_follow ROS 노드 — tracking_state → hybrid (STOP/REACTIVE/NAV2) cmd_vel/goal +
RECOVERY / WAITING_HINT lost recovery + close-follow lost prevention.

Control loop (NAV2_GOAL_HZ):
1. tracking_state 가 stale / not tracking → lost_duration 추적 → RECOVERY/WAITING_HINT/IDLE
2. distance_m EMA filter
3. close-follow flag 평가 (doorway 거리 + hysteresis) — target_distance / stop_max 동적
4. decide_follow_action → STOP / REACTIVE / NAV2 (hysteresis 적용)
5. Mode transition 시 정리 (cmd_vel zero / Nav2 cancel / PAN center 복귀)
6. 각 mode 별 action:
   - STOP: cmd_vel_raw zero, Nav2 cancel
   - REACTIVE: compute_reactive_cmd → cmd_vel_raw publish, Nav2 cancel
   - NAV2: estimate_follow_goal → send_goal (변화 > GOAL_CHANGE_THRESHOLD_M 일 때만)
   - RECOVERY: graph adjacency → PAN 슬로우 스캔 (각 후보 dwell)
   - WAITING_HINT: hint 무한 대기 + perception 자동 lock 시 자동 복귀

cmd_vel_raw → safety_filter → cmd_vel → robot 모터 (기존 흐름 유지).
"""
from __future__ import annotations

import math
import os
import time
from pathlib import Path

import rclpy
from ament_index_python.packages import get_package_share_directory
import tf2_geometry_msgs  # noqa: F401 — import side-effect 로 PoseStamped 변환 등록
from geometry_msgs.msg import Pose, PoseWithCovarianceStamped, Twist
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Float32, String
from tf2_ros import Buffer, TransformListener

from gogoping_msgs.msg import FollowTarget, TrackingState

from gogoping_follow.close_follow import (
    CloseFollowState,
    evaluate_close_follow,
    is_doorway_vertex,
    nearest_doorway_distance,
)
from gogoping_follow.config import (
    CLOSE_ANGLE_STABLE_DEG,
    CLOSE_ANGLE_STABLE_S,
    CLOSE_RELEASE_DIST_M,
    CLOSE_TRIGGER_DIST_M,
    CMD_VEL_RAW_TOPIC,
    FOLLOW_DISTANCE_CLOSE_M,
    FOLLOW_DISTANCE_M,
    GOAL_CHANGE_THRESHOLD_M,
    HINT_BACK_TURN_RATE_RAD_S,
    HINT_TOPIC,
    INITIAL_MODE_THRESHOLD_M,
    NAV2_GOAL_HZ,
    NAV2_MIN_DISTANCE_M,
    PAN_CMD_TOPIC,
    REACTIVE_ANGLE_DEADBAND_DEG,
    REACTIVE_DIST_DEADBAND_M,
    REACTIVE_KP_ANG,
    REACTIVE_KP_LIN,
    REACTIVE_MAX_ANG,
    REACTIVE_MAX_DISTANCE_M,
    REACTIVE_MAX_LIN,
    RECOVERY_DWELL_S,
    RECOVERY_HINT_DWELL_S,
    RECOVERY_LOST_TIMEOUT_S,
    RECOVERY_MAX_CANDIDATE_DIST_M,
    RECOVERY_PAN_CENTER_DEG,
    RECOVERY_PAN_FRONT_DEG,
    RECOVERY_PAN_LEFT_DEG,
    RECOVERY_PAN_MAX_DEG,
    RECOVERY_PAN_MIN_DEG,
    RECOVERY_PAN_RATE_DEG_S,
    RECOVERY_PAN_RIGHT_DEG,
    STATE_STALE_TIMEOUT_S,
    STOP_MAX_CLOSE_M,
    STOP_MAX_DISTANCE_M,
    TRACKING_STATE_EMA_ALPHA,
)
from gogoping_follow.follow_decision import DecisionMode, decide_follow_action
from gogoping_follow.nav2_client import Nav2Client
from gogoping_follow.reactive_control import compute_reactive_cmd
from gogoping_follow.recovery import (
    compute_candidates,
    compute_pan_step,
    hint_to_action,
)
from gogoping_follow.state_filter import TrackingStateEMA
from gogoping_follow.target_pose_estimator import estimate_follow_goal


class FollowNode(Node):
    def __init__(self) -> None:
        super().__init__("gogoping_follow_node")

        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)
        self._nav2 = Nav2Client(self)
        self._filter = TrackingStateEMA(alpha=TRACKING_STATE_EMA_ALPHA)

        # 추종 전용 BT — controller_id="FollowPersonPath" + goal_checker_id 도 분리.
        try:
            share_dir = get_package_share_directory('gogoping_follow')
            self._follow_bt = os.path.join(share_dir, 'behavior_trees', 'follow_person_bt.xml')
        except Exception as e:  # noqa: BLE001
            self.get_logger().warn(f"follow_person_bt.xml 경로 조회 실패: {e} — default BT 사용")
            self._follow_bt = ""

        self._target_id: str = ""
        self._last_state: TrackingState | None = None
        self._last_state_ts: float = 0.0
        self._last_scan: LaserScan | None = None
        self._robot_map_pose: Pose | None = None
        self._last_goal: Pose | None = None
        self._mode: DecisionMode = DecisionMode.IDLE

        # graph (close-follow doorway + RECOVERY adjacency)
        self._graph = None
        self._doorway_vertices: list[tuple[str, float, float]] = []
        self._load_graph()

        # close-follow 상태
        self._close_state = CloseFollowState()

        # RECOVERY 상태
        self._lost_since: float | None = None
        self._recovery_candidates: list = []
        self._recovery_idx: int = 0
        self._recovery_phase: str = "moving"  # "moving" or "dwelling"
        self._recovery_dwell_until: float = 0.0
        self._pan_current_deg: float = RECOVERY_PAN_CENTER_DEG

        # WAITING_HINT 상태
        self._pending_hint: str | None = None
        self._back_turn_until: float = 0.0
        self._back_turn_active: bool = False
        self._hint_dwell_until: float | None = None

        # Subscriptions
        self.create_subscription(
            TrackingState, "/gogoping/tracking_state", self._on_tracking_state, 10,
        )
        self.create_subscription(LaserScan, "/gogoping/scan", self._on_scan, 10)
        self.create_subscription(
            FollowTarget, "/gogoping/follow_target", self._on_follow_target, 10,
        )
        amcl_qos = QoSProfile(
            depth=10,
            reliability=QoSReliabilityPolicy.RELIABLE,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.create_subscription(
            PoseWithCovarianceStamped, "/amcl_pose", self._on_amcl_pose, amcl_qos,
        )
        self.create_subscription(String, HINT_TOPIC, self._on_hint, 10)

        # Publishers
        # cmd_vel_raw — STOP/REACTIVE/back-rotate 에서 사용. NAV2 동안엔 침묵 (Nav2 가 담당).
        self._cmd_vel_pub = self.create_publisher(Twist, CMD_VEL_RAW_TOPIC, 10)
        # PAN 명령 — RECOVERY / WAITING_HINT 에서 사용. servo_bridge 가 subscribe.
        self._pan_pub = self.create_publisher(Float32, PAN_CMD_TOPIC, 10)

        self.create_timer(1.0 / NAV2_GOAL_HZ, self._tick_control)

        self.get_logger().info(
            "FollowNode initialized — hybrid follow + close + recovery. "
            f"stop_max={STOP_MAX_DISTANCE_M}m reactive_max={REACTIVE_MAX_DISTANCE_M}m "
            f"nav2_min={NAV2_MIN_DISTANCE_M}m target={FOLLOW_DISTANCE_M}m | "
            f"close: doorway<{CLOSE_TRIGGER_DIST_M}m → target={FOLLOW_DISTANCE_CLOSE_M}m "
            f"stop_max={STOP_MAX_CLOSE_M}m | recovery_timeout={RECOVERY_LOST_TIMEOUT_S}s"
        )

    # ---------- graph loading ----------
    def _load_graph(self) -> None:
        """gogoping_navigation 의 graph 로드 — close-follow doorway + RECOVERY adjacency."""
        try:
            from gogoping_navigation.graph import Graph
            nav_share = Path(get_package_share_directory("gogoping_navigation"))
            wp = nav_share / "config" / "waypoints.yaml"
            lp = nav_share / "config" / "lanes.yaml"
            self._graph = Graph.from_yaml(wp, lanes_path=lp if lp.exists() else None)
            self._doorway_vertices = [
                (name, v.x, v.y) for name, v in self._graph.vertices().items()
                if is_doorway_vertex(name)
            ]
            self.get_logger().info(
                f"graph 로드 OK — doorway {len(self._doorway_vertices)} 개"
            )
        except Exception as e:  # noqa: BLE001
            self.get_logger().warn(
                f"graph 로드 실패 → close-follow / RECOVERY 비활성: {type(e).__name__}: {e}"
            )
            self._graph = None
            self._doorway_vertices = []

    # ---------- subscriptions ----------
    def _on_follow_target(self, msg: FollowTarget) -> None:
        if not msg.teacher_id:
            self._target_id = ""
            self._last_state = None
            self._filter.reset()
            self._enter_idle()
            self.get_logger().info("FollowTarget stop — IDLE")
            return
        self._target_id = msg.teacher_id
        self._filter.reset()
        self._mode = DecisionMode.IDLE
        self.get_logger().info(
            f"FollowTarget start: {msg.teacher_name} ({msg.teacher_id[:8]}...)"
        )

    def _on_tracking_state(self, msg: TrackingState) -> None:
        self._last_state = msg
        self._last_state_ts = time.time()

    def _on_scan(self, msg: LaserScan) -> None:
        self._last_scan = msg

    def _on_amcl_pose(self, msg: PoseWithCovarianceStamped) -> None:
        self._robot_map_pose = msg.pose.pose

    def _on_hint(self, msg: String) -> None:
        """음성/UI hint 수신 — WAITING_HINT 모드일 때만 처리."""
        direction = msg.data.strip()
        if not direction:
            return
        if self._mode != DecisionMode.WAITING_HINT:
            self.get_logger().debug(
                f"hint '{direction}' 수신 — 현재 mode {self._mode.value}, 무시"
            )
            return
        # hint 유효성 검사
        action = hint_to_action(
            direction,
            pan_left=RECOVERY_PAN_LEFT_DEG,
            pan_right=RECOVERY_PAN_RIGHT_DEG,
            pan_front=RECOVERY_PAN_FRONT_DEG,
            back_turn_rate_rad_s=HINT_BACK_TURN_RATE_RAD_S,
            dwell=RECOVERY_HINT_DWELL_S,
        )
        if action is None:
            self.get_logger().warn(f"unknown hint: '{direction}'")
            return
        self._pending_hint = direction
        self.get_logger().info(f"hint 수신: {direction} → 처리 시작")

    # ---------- control loop (NAV2_GOAL_HZ) ----------
    def _tick_control(self) -> None:
        if not self._target_id:
            return

        state = self._last_state
        now = time.time()
        stale = state is None or (now - self._last_state_ts) > STATE_STALE_TIMEOUT_S
        not_tracking = state is None or state.mode != "tracking" or not state.matched

        if stale or not_tracking:
            # lost_duration 시작/유지
            if self._lost_since is None:
                self._lost_since = now
            lost_duration = now - self._lost_since
            # decide — RECOVERY 진입 여부 결정 (NaN distance 사용)
            decision = decide_follow_action(
                distance_m=float("nan"),
                prev_mode=self._mode,
                stop_max=STOP_MAX_DISTANCE_M,
                reactive_max=REACTIVE_MAX_DISTANCE_M,
                nav2_min=NAV2_MIN_DISTANCE_M,
                initial_threshold=INITIAL_MODE_THRESHOLD_M,
                lost_duration_s=lost_duration,
                recovery_lost_timeout_s=RECOVERY_LOST_TIMEOUT_S,
            )
            new_mode = decision.mode
            if new_mode != self._mode:
                self._on_mode_transition(self._mode, new_mode)
                self._mode = new_mode
            if new_mode == DecisionMode.RECOVERY:
                self._tick_recovery(now)
            elif new_mode == DecisionMode.WAITING_HINT:
                self._tick_waiting_hint(now)
            else:
                # 짧은 lost 또는 IDLE 유지 — cmd_vel zero
                self._publish_zero()
            return

        # tracking 회복
        self._lost_since = None

        assert state is not None
        filtered = self._filter.update(
            distance_m=float(state.distance_m),
            angle_deg=float(state.angle_deg),
        )

        # close-follow flag 평가 (동적 target_distance / stop_max)
        if self._robot_map_pose is not None and self._doorway_vertices:
            rx = self._robot_map_pose.position.x
            ry = self._robot_map_pose.position.y
            doorway_dist = nearest_doorway_distance(rx, ry, self._doorway_vertices)
        else:
            doorway_dist = None
        self._close_state = evaluate_close_follow(
            prev=self._close_state,
            doorway_dist=doorway_dist,
            angle_deg=filtered.angle_deg,
            now=now,
            trigger_dist=CLOSE_TRIGGER_DIST_M,
            release_dist=CLOSE_RELEASE_DIST_M,
            angle_stable_deg=CLOSE_ANGLE_STABLE_DEG,
            angle_stable_s=CLOSE_ANGLE_STABLE_S,
        )
        if self._close_state.active:
            target_distance = FOLLOW_DISTANCE_CLOSE_M
            stop_max = STOP_MAX_CLOSE_M
        else:
            target_distance = FOLLOW_DISTANCE_M
            stop_max = STOP_MAX_DISTANCE_M

        decision = decide_follow_action(
            distance_m=filtered.distance_m,
            prev_mode=self._mode,
            stop_max=stop_max,
            reactive_max=REACTIVE_MAX_DISTANCE_M,
            nav2_min=NAV2_MIN_DISTANCE_M,
            initial_threshold=INITIAL_MODE_THRESHOLD_M,
            lost_duration_s=0.0,
            recovery_lost_timeout_s=RECOVERY_LOST_TIMEOUT_S,
        )
        new_mode = decision.mode

        if new_mode != self._mode:
            self._on_mode_transition(self._mode, new_mode)
            self._mode = new_mode

        if new_mode == DecisionMode.STOP:
            self._publish_zero()
        elif new_mode == DecisionMode.REACTIVE:
            cmd = compute_reactive_cmd(
                distance_m=filtered.distance_m,
                angle_deg=filtered.angle_deg,
                target_distance_m=target_distance,
                kp_lin=REACTIVE_KP_LIN,
                kp_ang=REACTIVE_KP_ANG,
                max_lin=REACTIVE_MAX_LIN,
                max_ang=REACTIVE_MAX_ANG,
                dist_deadband_m=REACTIVE_DIST_DEADBAND_M,
                angle_deadband_deg=REACTIVE_ANGLE_DEADBAND_DEG,
            )
            self._publish_cmd(cmd.linear_x, cmd.angular_z)
        elif new_mode == DecisionMode.NAV2:
            self._tick_nav2_send_goal(state)
        # IDLE: do nothing (already handled above by _enter_idle)

    def _tick_nav2_send_goal(self, state: TrackingState) -> None:
        """NAV2 모드 내 goal 갱신 — 변화 > GOAL_CHANGE_THRESHOLD_M 일 때만 send_goal."""
        try:
            estimate = estimate_follow_goal(
                angle_deg=float(state.angle_deg),
                scan=self._last_scan,
                tf_buffer=self._tf_buffer,
                robot_map_pose=self._robot_map_pose,
            )
        except Exception as e:  # noqa: BLE001 — tf2/numpy 예외 보호
            self.get_logger().warn(f"estimate_follow_goal 실패: {type(e).__name__}: {e}")
            return
        if estimate is None:
            return
        if (
            self._last_goal is None
            or _pose_distance(self._last_goal, estimate.goal) >= GOAL_CHANGE_THRESHOLD_M
        ):
            self._nav2.send_goal(estimate.goal, behavior_tree=self._follow_bt)
            self._last_goal = estimate.goal

    # ---------- RECOVERY ----------
    def _tick_recovery(self, now: float) -> None:
        """RECOVERY mode tick — graph adjacency PAN 슬로우 스캔."""
        # candidates 비어있으면 첫 진입 시 계산
        if not self._recovery_candidates:
            if self._robot_map_pose is None or self._graph is None:
                self.get_logger().warn("RECOVERY: amcl_pose 또는 graph 없음 → WAITING_HINT")
                self._mode = DecisionMode.WAITING_HINT
                self._publish_zero()
                return
            rx = self._robot_map_pose.position.x
            ry = self._robot_map_pose.position.y
            q = self._robot_map_pose.orientation
            ryaw = math.atan2(
                2.0 * (q.w * q.z + q.x * q.y),
                1.0 - 2.0 * (q.y * q.y + q.z * q.z),
            )
            # nearest_vertex + adjacency
            try:
                v_cur = self._graph.nearest_vertex(rx, ry)
                adj = self._graph._build_adjacency()[v_cur]  # noqa: SLF001
                adj_xy = [
                    (name, self._graph.vertices()[name].x, self._graph.vertices()[name].y)
                    for name, _w in adj
                ]
            except Exception as e:  # noqa: BLE001
                self.get_logger().warn(f"RECOVERY: graph query 실패: {e} → WAITING_HINT")
                self._mode = DecisionMode.WAITING_HINT
                self._publish_zero()
                return
            self._recovery_candidates = compute_candidates(
                robot_xy=(rx, ry),
                robot_yaw=ryaw,
                adjacent_vertices=adj_xy,
                max_dist=RECOVERY_MAX_CANDIDATE_DIST_M,
                pan_min=RECOVERY_PAN_MIN_DEG,
                pan_max=RECOVERY_PAN_MAX_DEG,
            )
            self._recovery_idx = 0
            self._recovery_phase = "moving"
            self.get_logger().info(
                f"RECOVERY: {len(self._recovery_candidates)} candidates — "
                f"{[c.vertex_name for c in self._recovery_candidates]}"
            )
            if not self._recovery_candidates:
                self._mode = DecisionMode.WAITING_HINT
                self._publish_zero()
                return

        # 현재 후보 처리
        if self._recovery_idx >= len(self._recovery_candidates):
            self.get_logger().info("RECOVERY: 모든 후보 실패 → WAITING_HINT")
            self._mode = DecisionMode.WAITING_HINT
            self._publish_zero()
            return
        c = self._recovery_candidates[self._recovery_idx]
        dt = 1.0 / NAV2_GOAL_HZ
        if self._recovery_phase == "moving":
            step = compute_pan_step(
                current=self._pan_current_deg, target=c.pan_deg,
                rate=RECOVERY_PAN_RATE_DEG_S, dt=dt,
            )
            self._pan_current_deg += step
            self._publish_pan(self._pan_current_deg)
            if abs(self._pan_current_deg - c.pan_deg) < 0.5:
                self._recovery_phase = "dwelling"
                self._recovery_dwell_until = now + RECOVERY_DWELL_S
        else:  # dwelling
            if now >= self._recovery_dwell_until:
                self._recovery_idx += 1
                self._recovery_phase = "moving"
        # cmd_vel zero (RECOVERY 동안 base 정지)
        self._publish_zero()

    # ---------- WAITING_HINT ----------
    def _tick_waiting_hint(self, now: float) -> None:
        """WAITING_HINT — hint 대기. perception 자동 lock 시 REACTIVE 복귀.

        hint 수신 시 RECOVERY-like 동작 (graph 무시, 직접 PAN 이동 + dwell).
        "back" hint 는 base 180° 회전 먼저.
        """
        if self._pending_hint is None:
            # 단순 대기 — cmd_vel zero, PAN center 유지
            self._publish_zero()
            return

        action = hint_to_action(
            self._pending_hint,
            pan_left=RECOVERY_PAN_LEFT_DEG,
            pan_right=RECOVERY_PAN_RIGHT_DEG,
            pan_front=RECOVERY_PAN_FRONT_DEG,
            back_turn_rate_rad_s=HINT_BACK_TURN_RATE_RAD_S,
            dwell=RECOVERY_HINT_DWELL_S,
        )
        assert action is not None  # _on_hint 에서 이미 검증
        dt = 1.0 / NAV2_GOAL_HZ

        # Phase 1: base 180° 회전 (back hint 만)
        if action.base_rotate_rad != 0.0 and not self._back_turn_active and self._hint_dwell_until is None:
            self._back_turn_active = True
            turn_duration = abs(action.base_rotate_rad) / HINT_BACK_TURN_RATE_RAD_S
            self._back_turn_until = now + turn_duration
            self.get_logger().info(
                f"hint 'back' — base 180° 회전 시작 ({turn_duration:.1f}s)"
            )
        if self._back_turn_active:
            if now < self._back_turn_until:
                twist = Twist()
                twist.angular.z = HINT_BACK_TURN_RATE_RAD_S * (
                    1.0 if action.base_rotate_rad > 0 else -1.0
                )
                self._cmd_vel_pub.publish(twist)
                return
            else:
                self._back_turn_active = False
                self._pan_current_deg = RECOVERY_PAN_CENTER_DEG
                self._publish_pan(RECOVERY_PAN_CENTER_DEG)

        # Phase 2: PAN 슬로우 이동 + dwell
        if abs(self._pan_current_deg - action.pan_target_deg) > 0.5:
            step = compute_pan_step(
                current=self._pan_current_deg, target=action.pan_target_deg,
                rate=RECOVERY_PAN_RATE_DEG_S, dt=dt,
            )
            self._pan_current_deg += step
            self._publish_pan(self._pan_current_deg)
            self._publish_zero()
            return

        # 도달 — dwell 시작 또는 진행
        if self._hint_dwell_until is None:
            self._hint_dwell_until = now + action.dwell_s
            self.get_logger().info(
                f"hint dwell 시작 — PAN {action.pan_target_deg}° "
                f"({action.dwell_s:.1f}s)"
            )

        if now >= self._hint_dwell_until:
            # dwell 만료 — 못 찾음 → WAITING_HINT 재진입 (hint 클리어)
            self.get_logger().info("hint dwell 만료 — 못 찾음, 다른 hint 대기")
            self._pending_hint = None
            self._hint_dwell_until = None
            self._pan_current_deg = RECOVERY_PAN_CENTER_DEG
            self._publish_pan(RECOVERY_PAN_CENTER_DEG)

        self._publish_zero()

    # ---------- mode transition handlers ----------
    def _on_mode_transition(self, old: DecisionMode, new: DecisionMode) -> None:
        """Mode 전환 시 정리 — cmd_vel zero / Nav2 cancel / filter reset / PAN reset."""
        # 이전이 NAV2 였고 새 mode 가 NAV2 아니면 goal cancel
        if old == DecisionMode.NAV2 and new != DecisionMode.NAV2:
            if self._last_goal is not None:
                self._nav2.cancel_current()
                self._last_goal = None
        # 이전이 REACTIVE 였고 새 mode 가 NAV2 면 residual cmd_vel 정지
        if old == DecisionMode.REACTIVE and new == DecisionMode.NAV2:
            self._publish_zero()
        # RECOVERY 진입 시 candidates 초기화 (다음 tick 에서 계산)
        if new == DecisionMode.RECOVERY and old != DecisionMode.RECOVERY:
            self._recovery_candidates = []
            self._recovery_idx = 0
            self._recovery_phase = "moving"
        # RECOVERY 탈출 시 PAN center 복귀
        if old == DecisionMode.RECOVERY and new != DecisionMode.RECOVERY:
            self._pan_current_deg = RECOVERY_PAN_CENTER_DEG
            self._publish_pan(RECOVERY_PAN_CENTER_DEG)
        # WAITING_HINT 탈출 시 (perception 자동 lock 등) hint 클리어
        if old == DecisionMode.WAITING_HINT and new != DecisionMode.WAITING_HINT:
            self._pending_hint = None
            self._hint_dwell_until = None
            self._back_turn_active = False
            self._pan_current_deg = RECOVERY_PAN_CENTER_DEG
            self._publish_pan(RECOVERY_PAN_CENTER_DEG)
            self.get_logger().info("WAITING_HINT 탈출 — hint 상태 클리어")
        # Mode 변경 logging
        self.get_logger().info(f"follow mode: {old.value} → {new.value}")

    def _enter_idle(self) -> None:
        """IDLE 진입 — Nav2 cancel + cmd_vel zero + PAN center + hint 클리어."""
        if self._last_goal is not None:
            self._nav2.cancel_current()
            self._last_goal = None
        self._publish_zero()
        if self._pan_current_deg != RECOVERY_PAN_CENTER_DEG:
            self._pan_current_deg = RECOVERY_PAN_CENTER_DEG
            self._publish_pan(RECOVERY_PAN_CENTER_DEG)
        # hint / recovery 상태 클리어
        self._pending_hint = None
        self._hint_dwell_until = None
        self._back_turn_active = False
        self._recovery_candidates = []
        self._recovery_idx = 0
        self._lost_since = None
        self._mode = DecisionMode.IDLE

    # ---------- cmd publishers ----------
    def _publish_zero(self) -> None:
        twist = Twist()
        self._cmd_vel_pub.publish(twist)

    def _publish_cmd(self, linear_x: float, angular_z: float) -> None:
        twist = Twist()
        twist.linear.x = linear_x
        twist.angular.z = angular_z
        self._cmd_vel_pub.publish(twist)

    def _publish_pan(self, deg: float) -> None:
        msg = Float32()
        msg.data = float(deg)
        self._pan_pub.publish(msg)


def _pose_distance(a: Pose, b: Pose) -> float:
    return math.hypot(
        b.position.x - a.position.x,
        b.position.y - a.position.y,
    )


def main() -> None:
    rclpy.init()
    node = FollowNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
