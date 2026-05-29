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
    CHASSIS_TURN_SCALE_LEFT,
    CHASSIS_TURN_SCALE_RIGHT,
    CLOSE_ANGLE_STABLE_DEG,
    CLOSE_ANGLE_STABLE_S,
    CLOSE_RELEASE_DIST_M,
    CLOSE_TRIGGER_DIST_M,
    CMD_VEL_RAW_TOPIC,
    FOLLOW_DISTANCE_CLOSE_M,
    FOLLOW_DISTANCE_M,
    FOLLOW_STATE_TOPIC,
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
    RECOVERY_BODY_MAX_TOTAL_DEG,
    RECOVERY_BODY_TURN_DEG,
    RECOVERY_BODY_TURN_RATE_RAD_S,
    RECOVERY_FULL_PAN_LEFT_DEG,
    RECOVERY_FULL_PAN_RIGHT_DEG,
    RECOVERY_HINT_DWELL_S,
    RECOVERY_LOST_TIMEOUT_S,
    RECOVERY_NARROW_PAN_HALF_DEG,
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
    TILT_CMD_TOPIC,
    TRACKING_STATE_EMA_ALPHA,
    VOICE_FOUND_TIMEOUT_S,
    VOICE_RESUME_TURN_RATE_RAD_S,
    VOICE_SEARCH_PAN_HOME_DEG,
    VOICE_SEARCH_PAN_LEFT_DEG,
    VOICE_SEARCH_PAN_RATE_DEG_S,
    VOICE_SEARCH_PAN_RIGHT_DEG,
    VOICE_TILT_HOME_DEG,
)
from gogoping_follow.follow_decision import DecisionMode, decide_follow_action
from gogoping_follow.nav2_client import Nav2Client
from gogoping_follow.reactive_control import compute_reactive_cmd
from gogoping_follow.recovery import (
    compute_candidates,  # noqa: F401 — legacy graph 모드 (현 미사용, 호환 import)
    compute_pan_step,
    hint_to_action,
)
from gogoping_follow.recovery_body_planner import (
    BodyPhase,
    BodyState,
    compute_pan_step as compute_body_pan_step,
    consume_body_turn,
    initial_state as recovery_initial_state,
    on_body_turn_complete,
    on_narrow_sweep_reach_target,
    on_sweep_complete,
)
from gogoping_follow.state_filter import TrackingStateEMA
from gogoping_follow.target_pose_estimator import estimate_follow_goal
from gogoping_follow.voice_search_planner import (
    SweepPhase,
    compute_voice_resume_yaw,
    compute_voice_sweep_step,
)


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

        # RECOVERY 상태 (Phase A/B/C body-search state machine)
        self._lost_since: float | None = None
        self._recovery_body: BodyState | None = None  # 진입 시 lazy init
        self._narrow_swept_once: bool = False  # narrow sweep 의 첫 끝 도달 여부
        self._pan_current_deg: float = RECOVERY_PAN_CENTER_DEG

        # WAITING_HINT 상태
        self._pending_hint: str | None = None
        self._back_turn_until: float = 0.0
        self._back_turn_active: bool = False
        self._hint_dwell_until: float | None = None

        # Voice-guided search 상태
        self._voice_sweep_phase: SweepPhase = SweepPhase.DONE
        self._voice_pan_found: float | None = None
        self._voice_found_until: float = 0.0
        self._voice_resume_yaw: float = 0.0
        self._voice_resume_dir: int = 0  # +1 (CCW) / -1 (CW) / 0 (회전 없음)
        self._voice_resume_until: float = 0.0
        self._voice_resume_done_actions: bool = False

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
        # PAN 명령 — RECOVERY / WAITING_HINT / VOICE_SEARCH 에서 사용.
        self._pan_pub = self.create_publisher(Float32, PAN_CMD_TOPIC, 10)
        # TILT 명령 — VOICE_RESUME 끝에 home 복귀.
        self._tilt_pub = self.create_publisher(Float32, TILT_CMD_TOPIC, 10)
        # follow_state publisher — mode 전이 시 publish. frontend WS subscribe.
        self._follow_state_pub = self.create_publisher(String, FOLLOW_STATE_TOPIC, 10)
        # 초기 mode publish (IDLE)
        self._publish_follow_state()

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
        """음성/UI hint 수신 — direction 별 분기.

        - "search" → VOICE_SEARCH 전이 (mode 무관, target_id 필요)
        - "resume" → VOICE_FOUND 일 때만 VOICE_RESUME 전이
        - left/right/front/back → WAITING_HINT 모드일 때만 처리 (기존)
        """
        direction = msg.data.strip()
        if not direction:
            return

        # Voice-guided search 명령
        if direction == "search":
            if not self._target_id:
                self.get_logger().warn("hint 'search' 수신 — target_id 미설정, 무시")
                return
            self.get_logger().info("hint 'search' 수신 → VOICE_SEARCH 전이")
            self._on_mode_transition(self._mode, DecisionMode.VOICE_SEARCH)
            return

        if direction == "resume":
            if self._mode != DecisionMode.VOICE_FOUND:
                self.get_logger().debug(
                    f"hint 'resume' 수신 — mode {self._mode.value}, 무시"
                )
                return
            self.get_logger().info("hint 'resume' 수신 → VOICE_RESUME 전이")
            self._on_mode_transition(DecisionMode.VOICE_FOUND, DecisionMode.VOICE_RESUME)
            return

        # 기존 left/right/front/back hint (WAITING_HINT 모드용)
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
            elif new_mode == DecisionMode.VOICE_SEARCH:
                self._tick_voice_search(now)
            elif new_mode == DecisionMode.VOICE_FOUND:
                self._tick_voice_found(now)
            elif new_mode == DecisionMode.VOICE_RESUME:
                self._tick_voice_resume(now)
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
        elif new_mode == DecisionMode.VOICE_SEARCH:
            self._tick_voice_search(now)
        elif new_mode == DecisionMode.VOICE_FOUND:
            self._tick_voice_found(now)
        elif new_mode == DecisionMode.VOICE_RESUME:
            self._tick_voice_resume(now)
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

    # ---------- RECOVERY (body-search state machine) ----------
    def _tick_recovery(self, now: float) -> None:
        """Phase A (FULL_SWEEP) → B (BODY_TURN) → C (NARROW_SWEEP), B/C 반복.

        본체 누적 ≥ MAX → WAITING_HINT. state 머신은 recovery_body_planner 참조.
        """
        # 첫 진입 — state 초기화
        if self._recovery_body is None:
            self._recovery_body = recovery_initial_state(
                current_pan_deg=self._pan_current_deg,
                pan_left_deg=RECOVERY_FULL_PAN_LEFT_DEG,
                pan_right_deg=RECOVERY_FULL_PAN_RIGHT_DEG,
            )
            self.get_logger().info(
                f"RECOVERY 진입 — Phase A FULL_SWEEP target="
                f"{self._recovery_body.pan_target_deg:.0f}°"
            )

        state = self._recovery_body
        dt = 1.0 / NAV2_GOAL_HZ

        if state.phase == BodyPhase.EXHAUSTED:
            self.get_logger().info("RECOVERY EXHAUSTED — WAITING_HINT 전이")
            self._mode = DecisionMode.WAITING_HINT
            self._recovery_body = None  # 다음 진입 시 reset
            self._publish_zero()
            return

        if state.phase in (BodyPhase.FULL_SWEEP, BodyPhase.NARROW_SWEEP):
            # PAN sweep — 목표 도달 시 다음 phase 전이
            next_pan, reached = compute_body_pan_step(
                current_deg=self._pan_current_deg,
                target_deg=state.pan_target_deg,
                rate_deg_s=RECOVERY_PAN_RATE_DEG_S,
                dt=dt,
            )
            self._pan_current_deg = next_pan
            self._publish_pan(next_pan)
            self._publish_zero()  # base 정지 (sweep 동안)

            if reached:
                if state.phase == BodyPhase.NARROW_SWEEP:
                    # narrow sweep: 첫 끝 도달이면 반대 끝으로 전환, 두 번째 도달이면 1 cycle 완료.
                    # _narrow_swept_once flag 로 양 끝 도달 여부 추적.
                    next_state = on_narrow_sweep_reach_target(
                        state, RECOVERY_PAN_FRONT_DEG, RECOVERY_NARROW_PAN_HALF_DEG,
                    )
                    if not self._narrow_swept_once:
                        self._narrow_swept_once = True
                        self._recovery_body = next_state
                        self.get_logger().info(
                            f"RECOVERY NARROW: 첫 끝 도달 → 반대 끝 "
                            f"{next_state.pan_target_deg:.0f}° 로 전환"
                        )
                    else:
                        self._narrow_swept_once = False
                        self._recovery_body = on_sweep_complete(
                            state, RECOVERY_FULL_PAN_LEFT_DEG,
                            RECOVERY_FULL_PAN_RIGHT_DEG,
                            RECOVERY_BODY_TURN_DEG,
                            RECOVERY_BODY_MAX_TOTAL_DEG,
                        )
                        self.get_logger().info(
                            f"RECOVERY NARROW cycle 완료 → BODY_TURN "
                            f"(누적 {self._recovery_body.total_body_turn_deg:.0f}°)"
                        )
                else:
                    self._recovery_body = on_sweep_complete(
                        state, RECOVERY_FULL_PAN_LEFT_DEG,
                        RECOVERY_FULL_PAN_RIGHT_DEG,
                        RECOVERY_BODY_TURN_DEG,
                        RECOVERY_BODY_MAX_TOTAL_DEG,
                    )
                    self.get_logger().info(
                        f"RECOVERY FULL_SWEEP 도달 (PAN {next_pan:.0f}°) → BODY_TURN "
                        f"yaw_dir={self._recovery_body.yaw_dir}"
                    )
            return

        if state.phase == BodyPhase.BODY_TURN:
            # chassis 비대칭 보정 — yaw_dir 부호에 따라 effective_rate scale.
            # angular.z 와 duration 계산에 같은 effective_rate 사용 (일관성).
            scale = CHASSIS_TURN_SCALE_LEFT if state.yaw_dir > 0 else CHASSIS_TURN_SCALE_RIGHT
            effective_rate = RECOVERY_BODY_TURN_RATE_RAD_S * scale
            twist = Twist()
            twist.angular.z = effective_rate * state.yaw_dir
            self._cmd_vel_pub.publish(twist)
            self._publish_pan(self._pan_current_deg)
            next_state, completed = consume_body_turn(
                state, effective_rate, dt,
            )
            if completed:
                self._recovery_body = on_body_turn_complete(
                    next_state,
                    current_pan_deg=self._pan_current_deg,
                    narrow_pan_front_deg=RECOVERY_PAN_FRONT_DEG,
                    narrow_pan_half_deg=RECOVERY_NARROW_PAN_HALF_DEG,
                )
                self.get_logger().info(
                    f"RECOVERY BODY_TURN 완료 → NARROW_SWEEP target="
                    f"{self._recovery_body.pan_target_deg:.0f}°"
                )
            else:
                self._recovery_body = next_state
            return

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

        # Phase 1: base 180° 회전 (back hint). chassis 비대칭 보정 적용.
        yaw_dir_hint = 1.0 if action.base_rotate_rad > 0 else -1.0
        hint_scale = CHASSIS_TURN_SCALE_LEFT if yaw_dir_hint > 0 else CHASSIS_TURN_SCALE_RIGHT
        hint_effective_rate = HINT_BACK_TURN_RATE_RAD_S * hint_scale
        if action.base_rotate_rad != 0.0 and not self._back_turn_active and self._hint_dwell_until is None:
            self._back_turn_active = True
            turn_duration = abs(action.base_rotate_rad) / hint_effective_rate
            self._back_turn_until = now + turn_duration
            self.get_logger().info(
                f"hint 'back' — base 180° 회전 시작 ({turn_duration:.1f}s)"
            )
        if self._back_turn_active:
            if now < self._back_turn_until:
                twist = Twist()
                twist.angular.z = hint_effective_rate * yaw_dir_hint
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

    # ---------- Voice-guided search ----------
    def _tick_voice_search(self, now: float) -> None:
        """VOICE_SEARCH — home → left → right → home sweep. matched 시 즉시 VOICE_FOUND."""
        # 사람 발견 체크
        state = self._last_state
        if state is not None and state.matched and state.mode == "tracking":
            self._voice_pan_found = self._pan_current_deg
            self.get_logger().info(
                f"VOICE_SEARCH: 발견 (PAN={self._voice_pan_found:.1f}°) → VOICE_FOUND"
            )
            self._on_mode_transition(DecisionMode.VOICE_SEARCH, DecisionMode.VOICE_FOUND)
            self._publish_zero()
            return

        # sweep 진행
        if self._voice_sweep_phase == SweepPhase.DONE:
            self.get_logger().info("VOICE_SEARCH: sweep 끝 (못 찾음) → IDLE")
            self._on_mode_transition(DecisionMode.VOICE_SEARCH, DecisionMode.IDLE)
            self._publish_zero()
            return

        dt = 1.0 / NAV2_GOAL_HZ
        next_pan, next_phase = compute_voice_sweep_step(
            current=self._pan_current_deg,
            phase=self._voice_sweep_phase,
            rate=VOICE_SEARCH_PAN_RATE_DEG_S,
            dt=dt,
            pan_home=VOICE_SEARCH_PAN_HOME_DEG,
            pan_left=VOICE_SEARCH_PAN_LEFT_DEG,
            pan_right=VOICE_SEARCH_PAN_RIGHT_DEG,
        )
        self._pan_current_deg = next_pan
        self._voice_sweep_phase = next_phase
        self._publish_pan(self._pan_current_deg)
        self._publish_zero()

    def _tick_voice_found(self, now: float) -> None:
        """VOICE_FOUND — PAN 정지 + base 정지. 사용자 'resume' 명령 대기.

        VOICE_FOUND_TIMEOUT_S 초과 시 IDLE 복귀.
        """
        self._publish_zero()
        if now >= self._voice_found_until:
            self.get_logger().info("VOICE_FOUND: timeout → IDLE")
            self._on_mode_transition(DecisionMode.VOICE_FOUND, DecisionMode.IDLE)

    def _tick_voice_resume(self, now: float) -> None:
        """VOICE_RESUME — base 회전 + 회전 끝나면 PAN/TILT home + IDLE 전이."""
        if now < self._voice_resume_until and self._voice_resume_dir != 0:
            # chassis 비대칭 보정 — yaw_dir 부호에 따라 angular.z scale.
            scale = CHASSIS_TURN_SCALE_LEFT if self._voice_resume_dir > 0 else CHASSIS_TURN_SCALE_RIGHT
            twist = Twist()
            twist.angular.z = VOICE_RESUME_TURN_RATE_RAD_S * scale * self._voice_resume_dir
            self._cmd_vel_pub.publish(twist)
            return

        # 회전 끝 — 한 번만 PAN/TILT home publish
        if not self._voice_resume_done_actions:
            self._publish_zero()
            self._pan_current_deg = VOICE_SEARCH_PAN_HOME_DEG
            self._publish_pan(VOICE_SEARCH_PAN_HOME_DEG)
            self._publish_tilt(VOICE_TILT_HOME_DEG)
            self._voice_resume_done_actions = True
            self.get_logger().info("VOICE_RESUME: 회전 끝 + PAN/TILT home → IDLE")

        # IDLE 전이
        self._on_mode_transition(DecisionMode.VOICE_RESUME, DecisionMode.IDLE)

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
        # RECOVERY 진입 시 body-search state 초기화 (다음 tick 에서 lazy init)
        if new == DecisionMode.RECOVERY and old != DecisionMode.RECOVERY:
            self._recovery_body = None
            self._narrow_swept_once = False
        # RECOVERY 탈출 시 PAN center 복귀 + state 클리어
        if old == DecisionMode.RECOVERY and new != DecisionMode.RECOVERY:
            self._pan_current_deg = RECOVERY_PAN_CENTER_DEG
            self._publish_pan(RECOVERY_PAN_CENTER_DEG)
            self._recovery_body = None
            self._narrow_swept_once = False
            self._publish_zero()  # BODY_TURN 잔여 cmd_vel 정지
        # WAITING_HINT 탈출 시 (perception 자동 lock 등) hint 클리어
        if old == DecisionMode.WAITING_HINT and new != DecisionMode.WAITING_HINT:
            self._pending_hint = None
            self._hint_dwell_until = None
            self._back_turn_active = False
            self._pan_current_deg = RECOVERY_PAN_CENTER_DEG
            self._publish_pan(RECOVERY_PAN_CENTER_DEG)
            self.get_logger().info("WAITING_HINT 탈출 — hint 상태 클리어")
        # VOICE_SEARCH 진입 시 sweep phase 초기화 + 발견 위치 초기화
        if new == DecisionMode.VOICE_SEARCH and old != DecisionMode.VOICE_SEARCH:
            self._voice_sweep_phase = SweepPhase.TO_HOME_START
            self._voice_pan_found = None
        # VOICE_FOUND 진입 시 timeout 설정
        if new == DecisionMode.VOICE_FOUND and old != DecisionMode.VOICE_FOUND:
            self._voice_found_until = time.time() + VOICE_FOUND_TIMEOUT_S
        # VOICE_RESUME 진입 — yaw + 회전 종료 시각. duration 도 chassis 보정 반영.
        if new == DecisionMode.VOICE_RESUME and old != DecisionMode.VOICE_RESUME:
            pan = self._voice_pan_found if self._voice_pan_found is not None else 90.0
            yaw = compute_voice_resume_yaw(pan)
            self._voice_resume_yaw = abs(yaw)
            self._voice_resume_dir = 1 if yaw > 0 else (-1 if yaw < 0 else 0)
            vr_scale = CHASSIS_TURN_SCALE_LEFT if self._voice_resume_dir > 0 else CHASSIS_TURN_SCALE_RIGHT
            vr_effective_rate = VOICE_RESUME_TURN_RATE_RAD_S * vr_scale
            self._voice_resume_until = time.time() + (
                self._voice_resume_yaw / vr_effective_rate
                if self._voice_resume_yaw > 0 else 0.0
            )
            self._voice_resume_done_actions = False
        # Mode 변경 logging + follow_state publish
        self.get_logger().info(f"follow mode: {old.value} → {new.value}")
        self._mode = new  # caller 가 직후 또 set 해도 무해 — 여기서 확정해 publish 정확.
        self._publish_follow_state()

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
        self._recovery_body = None
        self._narrow_swept_once = False
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

    def _publish_tilt(self, deg: float) -> None:
        msg = Float32()
        msg.data = float(deg)
        self._tilt_pub.publish(msg)

    def _publish_follow_state(self) -> None:
        """현재 mode 를 /gogoping/follow_state 토픽으로 publish (frontend WS subscribe)."""
        msg = String()
        msg.data = self._mode.value
        self._follow_state_pub.publish(msg)


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
