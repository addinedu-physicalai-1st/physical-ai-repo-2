"""rclpy 기반 GameRunner 노드 — runner.run() 이 lazy import 한다.

이 모듈을 직접 import 하려면 ROS2 환경이 source 되어 있어야 한다 (`source /opt/ros/jazzy/setup.bash`).
"""
from __future__ import annotations

import importlib
import logging
import time
from pathlib import Path
from typing import Any

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

# control_msgs 는 GripperCommand action 을 위해서만 필요 — runner 전체 import 가
# control_msgs 미설치 환경에서 깨지지 않게 lazy 로 두지 않고 가드.
try:
    from control_msgs.action import GripperCommand  # type: ignore[import-not-found]

    _HAS_GRIPPER_ACTION = True
except ImportError:  # noqa: BLE001
    GripperCommand = None  # type: ignore[assignment, misc]
    _HAS_GRIPPER_ACTION = False

from noriarm_framework.manifest import ArmSpec, GameConfig
from noriarm_framework.policy import (
    Action,
    GameContext,
    IdleAction,
    JointTargetsAction,
    Observation,
    Policy,
    ReplayTrajectoryAction,
)
from noriarm_framework.runner import RunnerConfig
from noriarm_framework.trajectory import (
    build_joint_trajectory,
    deg_to_rad,
    load_trajectory,
)

logger = logging.getLogger(__name__)


def _publish_mode_for(arm: ArmSpec, target: str) -> str:
    """매니페스트의 backend 값으로 publish 모드를 결정.

    - 'joint_state_only' → /joint_states 직접 publish (three.js URDF 뷰어용)
    - 그 외 (gazebo, dynamixel, 등) → ros2_control 의 controller_topic 으로 JointTrajectory
    """
    backend = arm.backend(target).get("backend", "")
    return "joint_state" if backend == "joint_state_only" else "controller"


def load_policy(config: GameConfig) -> Policy:
    """매니페스트의 policy.module 을 동적 import 해 Policy 인스턴스를 만든다."""
    module = importlib.import_module(config.policy.module)
    if not hasattr(module, "build_policy"):
        raise RuntimeError(f"{config.policy.module}: build_policy(config) 함수가 없습니다")
    policy: Policy = module.build_policy(config)
    if not isinstance(policy, Policy):
        raise RuntimeError(
            f"{config.policy.module}.build_policy() 가 Policy 프로토콜을 만족하지 않습니다"
        )
    return policy


class GameRunner(Node):
    def __init__(self, cfg: RunnerConfig, policy: Policy) -> None:
        super().__init__("noriarm_game_runner")
        self._cfg = cfg
        self._policy = policy
        self._game_dir = (
            cfg.config.source_path.parent if cfg.config.source_path else Path.cwd()
        )

        # 백엔드 별 publisher: 'joint_state_only' 는 /joint_states 직접 publish, 그 외는
        # ros2_control 의 controller_topic 으로 JointTrajectory publish.
        self._arm_publishers: dict[str, Any] = {}
        self._arm_modes: dict[str, str] = {}  # arm_id -> 'joint_state' | 'controller'
        for arm in cfg.config.arms:
            mode = _publish_mode_for(arm, cfg.target)
            self._arm_modes[arm.id] = mode
            if mode == "joint_state":
                topic = arm.backend(cfg.target).get("joint_state_topic", "/joint_states")
                pub = self.create_publisher(JointState, topic, 10)
                names = arm.backend(cfg.target).get("joint_state_names")
                if not names:
                    raise RuntimeError(
                        f"arm={arm.id}: backend=joint_state_only 인데 joint_state_names 가 매니페스트에 없음"
                    )
                self.get_logger().info(
                    f"publisher 준비: arm={arm.id} mode=joint_state topic={topic} joints={names}"
                )
            else:
                pub = self.create_publisher(JointTrajectory, arm.controller_topic, 10)
                self.get_logger().info(
                    f"publisher 준비: arm={arm.id} mode=controller topic={arm.controller_topic} "
                    f"joints={arm.controller_joint_names}"
                )
            self._arm_publishers[arm.id] = pub

        # OMX-F bringup 의 gripper_controller 는 JointTrajectoryController 가 아니라
        # GripperActionController — `/gripper_controller/gripper_cmd` action 만 받는다.
        # 따라서 arm_controller 로 보내는 trajectory 의 6번째 컬럼 (gripper) 은
        # 자동으로 잘려나가고 손가락은 명령을 받지 못한다. replay 시 첫 프레임의 gripper
        # 값을 한 번 action goal 로 보내 closed-pose 진입시킨다 (animation 없음).
        self._gripper_action_name = "/gripper_controller/gripper_cmd"
        if _HAS_GRIPPER_ACTION:
            self._gripper_client: ActionClient | None = ActionClient(
                self, GripperCommand, self._gripper_action_name,
            )
        else:
            self._gripper_client = None
            self.get_logger().warn(
                "control_msgs.action.GripperCommand import 실패 — 그리퍼 명령 비활성화"
            )

        # ACT 정책이면 카메라 + /joint_states 구독 셋업 — observation 채우기용.
        self._obs_capture: dict | None = None
        if cfg.config.policy.kind == "act":
            self._setup_act_observation_capture()

    def _setup_act_observation_capture(self) -> None:
        from noriarm_framework.observation_capture import LatestFrameBuffer, LatestJointState

        arm = self._cfg.config.arms[0]
        camera_keys = tuple(c.id for c in self._cfg.config.cameras) or ("top",)
        self._obs_capture = {
            "arm_id": arm.id,
            "frames": LatestFrameBuffer(keys=camera_keys),
            "joint_state": LatestJointState(expected_names=arm.controller_joint_names),
        }
        # /joint_states 구독 — sim/real 동일.
        topic = arm.backend(self._cfg.target).get("joint_state_topic", "/joint_states")
        self.create_subscription(
            JointState, topic, self._on_joint_state_for_act, 10
        )
        # 카메라는 cv2.VideoCapture 로 백그라운드 스레드에서 push.
        self._start_camera_capture_threads(camera_keys)

    def _on_joint_state_for_act(self, msg) -> None:
        if self._obs_capture is None:
            return
        self._obs_capture["joint_state"].update(list(msg.name), list(msg.position))

    def _start_camera_capture_threads(self, camera_keys: tuple[str, ...]) -> None:
        import threading
        import cv2  # lazy — OX 퀴즈는 안 씀

        for i, key in enumerate(camera_keys):
            t = threading.Thread(
                target=self._camera_capture_loop, args=(key, i), daemon=True
            )
            t.start()

    def _camera_capture_loop(self, key: str, device_index: int) -> None:
        import cv2

        cap = cv2.VideoCapture(device_index)
        if not cap.isOpened():
            self.get_logger().warn(
                f"카메라 {key} (index={device_index}) open 실패 — obs.images 미공급"
            )
            return
        try:
            while rclpy.ok():
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                self._obs_capture["frames"].put(key, frame)
        finally:
            cap.release()

    def run(self) -> None:
        ctx = GameContext(
            game_name=self._cfg.config.name,
            target=self._cfg.target,
            extra=dict(self._cfg.inputs),
        )
        self._policy.reset(ctx)
        self.get_logger().info(
            f"게임 시작: name={self._cfg.config.name} target={self._cfg.target} "
            f"rate_hz={self._cfg.config.runtime.rate_hz} inputs={self._cfg.inputs}"
        )
        # 게임 시작 시점에 그리퍼를 한 번 닫는다 — 사용자가 첫 답을 누르기 전부터 closed pose.
        # 이전 세션이 open 으로 끝났거나 bringup 직후 초기 0.0 rad (사용자 보드에선 미닫힘)
        # 인 상태를 보정. action 서버 미연결이면 경고만, 게임은 계속 진행.
        self._send_gripper_close(context="game-start")

        period = 1.0 / self._cfg.config.runtime.rate_hz
        deadline = time.monotonic() + self._cfg.config.runtime.episode_timeout_s
        step = 0
        while rclpy.ok() and time.monotonic() < deadline:
            if self._cfg.max_steps is not None and step >= self._cfg.max_steps:
                break
            obs = self._sense(step)
            action = self._policy.step(obs)
            terminated = self._apply(action)
            step += 1
            if terminated:
                self.get_logger().info("정책이 종료를 신호 — 루프 탈출")
                break
            rclpy.spin_once(self, timeout_sec=period)

        self.get_logger().info(f"게임 종료: steps={step}")

    def _sense(self, step: int) -> Observation:
        """ACT 모드일 때만 실제 obs 채움. 그 외 (OX 퀴즈 등) 빈 obs."""
        if not hasattr(self, "_obs_capture") or self._obs_capture is None:
            return Observation(timestamp=float(step), extra=dict(self._cfg.inputs))
        capture: dict = self._obs_capture
        images = capture["frames"].snapshot()
        js = capture["joint_state"].snapshot()
        joint_states = {capture["arm_id"]: js} if js is not None else None
        return Observation(
            images=images if images else None,
            joint_states=joint_states,
            timestamp=float(step),
            extra=dict(self._cfg.inputs),
        )

    def _apply(self, action: Action) -> bool:
        if isinstance(action, IdleAction):
            return False
        if isinstance(action, ReplayTrajectoryAction):
            self._apply_replay(action)
            return True
        if isinstance(action, JointTargetsAction):
            self._apply_joint_targets(action)
            return False
        self.get_logger().warn(f"알 수 없는 action: {action!r}")
        return False

    def _apply_replay(self, action: ReplayTrajectoryAction) -> None:
        arm = self._select_arm(getattr(action, "arm_id", None))
        traj_path = self._game_dir / action.name
        traj = load_trajectory(traj_path)
        mode = self._arm_modes[arm.id]
        self.get_logger().info(
            f"replay 로드: name={action.name} frames={traj.num_frames} hz={traj.hz} mode={mode}"
        )
        if mode == "joint_state":
            self._replay_as_joint_states(arm, traj)
        else:
            # 실 하드웨어 — arm trajectory 발사 전에 gripper closed-pose 한 번 보낸다.
            # JointTrajectory 는 5축만 받고 gripper 는 별도 action 으로 가야 한다.
            self._maybe_send_initial_gripper(arm, traj)
            self._replay_as_trajectory(arm, traj)

    # OMX-F 그리퍼 closed pose (rad).
    # 업스트림 GUI 는 0.0=close / 1.0=open 으로 명목값을 쓰지만 dynamixel_hardware_interface
    # 가 URDF 라디안 → 모터 raw ticks 변환에 오프셋을 넣기 때문에 실제 "닫힘"이 잡히는
    # URDF 라디안은 캘리브레이션에 따라 다르다 (이 보드는 0.0 으로는 잡 안 닫혀짐 확인).
    # 모터 16 은 Operating Mode 5 (current-based position) + Current Limit 600 mA 라서
    # **닫힘 한계점을 지나는 라디안을 줘도 모터가 stall 검출 → 안전 정지**.
    # -1.0 으로 보내 jaws 가 닿을 때까지 강제 — 닿으면 600 mA 에 막혀 그 자리 유지.
    # 만약 이 방향이 오히려 열리면 +1.5 로 부호 뒤집어서 시도.
    GRIPPER_CLOSED_RAD = -1.0

    # arm_controller 가 소유할 수 있는 그리퍼 joint 이름. omx_f_follower_ai 구성에서
    # arm_controller 는 [joint1..joint5, gripper_joint_1] 6축을 소유 — 별도 gripper_controller
    # 가 없다. 이 이름이 controller_joint_names 에 포함돼 있으면 inline 오버라이드 경로,
    # 아니면 _maybe_send_initial_gripper 로 별도 action 호출 (omx_f 구성).
    _GRIPPER_JOINT_NAME = "gripper_joint_1"

    # max_effort 0.0 은 controller 에 따라 "토크 0 = 안 움직임" 으로 해석되기도 한다.
    # OMX-F dynamixel xl330 의 명시적 안전한 값 — current_based_position 모드에서
    # 충분한 토크지만 사람 손 잡으면 멈출 정도. params_.max_effort 가 노드 설정에서
    # 0 이면 우리 값으로 덮어쓴다.
    GRIPPER_MAX_EFFORT = 5.0

    def _send_gripper_close(self, *, context: str) -> None:
        """그리퍼 action server 에 닫힘 goal 한 번 송신 (omx_f 구성용).

        context 는 로그 prefix — 'game-start' / 'replay' / 'tune' 등.
        action 서버 미연결·거부·타임아웃은 경고만 남기고 진행 — 게임을 막지 않는다.
        """
        if self._gripper_client is None or GripperCommand is None:
            return
        log = self.get_logger()
        log.info(
            f"[gripper:{context}] 닫기 시도: action='{self._gripper_action_name}' "
            f"position={self.GRIPPER_CLOSED_RAD:.3f} rad max_effort={self.GRIPPER_MAX_EFFORT}"
        )
        if not self._gripper_client.wait_for_server(timeout_sec=2.0):
            log.warn(
                f"[gripper:{context}]   ✗ action server '{self._gripper_action_name}' 미확인 (2s) — "
                f"controller_manager 의 gripper_controller 가 spawn 됐는지 확인:\n"
                f"     ros2 control list_controllers"
            )
            return
        goal = GripperCommand.Goal()
        goal.command.position = float(self.GRIPPER_CLOSED_RAD)
        goal.command.max_effort = float(self.GRIPPER_MAX_EFFORT)
        send_future = self._gripper_client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, send_future, timeout_sec=2.0)
        goal_handle = send_future.result() if send_future.done() else None
        if goal_handle is None or not goal_handle.accepted:
            log.warn(f"[gripper:{context}]   ✗ goal 거부됨 (handle={goal_handle})")
            return
        log.info(f"[gripper:{context}]   ✓ goal accepted — 결과 대기 (최대 5s)")
        result_future = goal_handle.get_result_async()
        rclpy.spin_until_future_complete(self, result_future, timeout_sec=5.0)
        if result_future.done():
            res = result_future.result()
            log.info(
                f"[gripper:{context}]   ✓ 닫기 완료: status={res.status} "
                f"reached={res.result.reached_goal} stalled={res.result.stalled} "
                f"position={res.result.position:.3f} effort={res.result.effort:.3f}"
            )
        else:
            log.warn(f"[gripper:{context}]   ⚠ 5s 안에 결과 안 옴 — 진행")

    def _maybe_send_initial_gripper(self, arm: ArmSpec, traj) -> None:
        """replay 직전 그리퍼 닫기 — 게임 중에 살짝 열리는 일이 있으면 매 답마다 재 닫음.

        그리퍼가 arm_controller 의 joint 로 들어가 있는 구성 (omx_f_follower_ai) 에선
        `_replay_as_trajectory` 가 컬럼 오버라이드로 처리하므로 여기서는 스킵 —
        존재하지 않는 action server 를 2초 기다리는 낭비 방지.
        """
        if self._GRIPPER_JOINT_NAME in arm.controller_joint_names:
            return
        n_arm = len(arm.controller_joint_names)
        if traj.num_columns <= n_arm:
            return  # gripper column 없음 (5축 traj)
        self._send_gripper_close(context="replay")

    def _replay_as_trajectory(self, arm: ArmSpec, traj) -> None:
        """ros2_control 의 JointTrajectoryController 로 한 번에 전송."""
        msg = build_joint_trajectory(traj, arm.controller_joint_names)
        self._override_gripper_column_if_present(msg, arm)
        publisher = self._arm_publishers[arm.id]
        if not self._wait_for_subscriber(publisher):
            self.get_logger().error(
                f"controller subscriber 가 안 올라옴 — topic={arm.controller_topic}"
            )
            return
        publisher.publish(msg)
        self.get_logger().info(
            f"publish 완료: points={len(msg.points)} duration={traj.duration_s:.2f}s"
        )
        end = time.monotonic() + traj.duration_s + 0.5
        while rclpy.ok() and time.monotonic() < end:
            rclpy.spin_once(self, timeout_sec=0.05)

    def _override_gripper_column_if_present(self, msg: JointTrajectory, arm: ArmSpec) -> None:
        """JointTrajectory 의 gripper_joint_1 컬럼을 GRIPPER_CLOSED_RAD 로 덮어쓴다.

        omx_f_follower_ai 구성에서 arm_controller 가 gripper 까지 6축 소유 — 녹화된
        lerobot range_0_100 정규값은 deg_to_rad 로 잘못 변환되므로 무시하고, 모든
        포인트에 동일한 닫힘 각도를 박는다. 그리퍼가 controller_joint_names 에 없으면
        no-op (5축 구성에서는 이 함수가 아무 일도 하지 않는다).
        """
        try:
            idx = list(msg.joint_names).index(self._GRIPPER_JOINT_NAME)
        except ValueError:
            return  # 그리퍼 미포함 — 별도 action 경로가 처리.
        for point in msg.points:
            # JointTrajectoryPoint.positions 는 array.array — 새 list 로 교체.
            positions = list(point.positions)
            if idx < len(positions):
                positions[idx] = float(self.GRIPPER_CLOSED_RAD)
                point.positions = positions
        self.get_logger().info(
            f"gripper 컬럼 (idx={idx}, name={self._GRIPPER_JOINT_NAME}) 을 "
            f"{self.GRIPPER_CLOSED_RAD:.3f} rad 으로 덮어썼다 (frames={len(msg.points)})"
        )

    def _replay_as_joint_states(self, arm: ArmSpec, traj) -> None:
        """/joint_states 로 frame-by-frame publish — three.js URDF 뷰어용 경량 경로."""
        backend = arm.backend(self._cfg.target)
        names: list[str] = list(backend["joint_state_names"])
        publisher = self._arm_publishers[arm.id]
        # subscriber (rosbridge_websocket 또는 robot_state_publisher) 매칭은 sub-zero 일 수도
        # 있다 — 그 경우 그냥 broadcast (DDS 메시지는 늦게 join 한 subscriber 도 못 받지만
        # 60ms 페이즈 내에는 매칭됨).
        sliced = traj.slice_columns(len(names))
        period = 1.0 / sliced.hz
        self.get_logger().info(
            f"joint_state replay 시작: frames={sliced.num_frames} duration={sliced.duration_s:.2f}s "
            f"topic={backend.get('joint_state_topic', '/joint_states')}"
        )
        for i, frame in enumerate(sliced.frames_deg):
            if not rclpy.ok():
                break
            msg = JointState()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.name = names
            msg.position = deg_to_rad(frame)
            publisher.publish(msg)
            if i % 60 == 0:
                self.get_logger().debug(
                    f"  frame {i}/{sliced.num_frames} ({i / sliced.num_frames * 100:.0f}%)"
                )
            # 다음 frame 까지 spin + sleep.
            rclpy.spin_once(self, timeout_sec=period)
        self.get_logger().info("joint_state replay 완료")

    def _apply_joint_targets(self, action: JointTargetsAction) -> None:
        arm = self._select_arm(action.arm_id)
        msg = JointTrajectory()
        msg.joint_names = list(action.joint_names)
        point = JointTrajectoryPoint()
        point.positions = list(action.positions)
        sec = int(action.duration_s)
        point.time_from_start.sec = sec
        point.time_from_start.nanosec = int((action.duration_s - sec) * 1e9)
        msg.points.append(point)
        self._arm_publishers[arm.id].publish(msg)

    def _select_arm(self, arm_id: str | None) -> ArmSpec:
        arms = self._cfg.config.arms
        if not arms:
            raise RuntimeError("매니페스트에 arm 이 없음")
        if arm_id:
            return self._cfg.config.arm_by_id(arm_id)
        if len(arms) == 1:
            return arms[0]
        raise RuntimeError(
            f"action.arm_id 가 없고 arm 이 {len(arms)}개 — 어느 팔로 보낼지 모름"
        )

    def _wait_for_subscriber(self, publisher: Any) -> bool:
        timeout = self._cfg.effective_subscriber_timeout()
        self.get_logger().info(
            f"controller subscriber 매칭 대기... (최대 {timeout:.0f}s — Gazebo/arm_controller 활성화 기다리는 중)"
        )
        start = time.monotonic()
        deadline = start + timeout
        next_log = start + 5.0
        while time.monotonic() < deadline:
            if publisher.get_subscription_count() > 0:
                self.get_logger().info(
                    f"subscriber 매칭됨 ({time.monotonic() - start:.1f}s)"
                )
                return True
            rclpy.spin_once(self, timeout_sec=0.1)
            now = time.monotonic()
            if now >= next_log:
                self.get_logger().info(f"  ...아직 대기 중 ({now - start:.0f}s 경과)")
                next_log = now + 5.0
        return False


def run_with_ros(cfg: RunnerConfig) -> None:
    """rclpy 라이프사이클 + GameRunner 실행.

    sim 인프라 (Gazebo / rosbridge / ...) spawn 은 더 이상 runner 책임이 아니다 —
    Control Server 가 SSE 로 직접 다리 역할을 하고, 실제 ROS 노드 spawn 이 필요한 게임이
    있으면 그 시점에 Control Server 의 세션 매니저 (SR-NORI-007) 가 처리한다.
    """
    policy = load_policy(cfg.config)
    rclpy.init()
    try:
        runner = GameRunner(cfg, policy)
        try:
            runner.run()
        finally:
            runner.destroy_node()
    finally:
        rclpy.shutdown()
