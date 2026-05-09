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
from rclpy.node import Node
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

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
        return Observation(timestamp=float(step), extra=dict(self._cfg.inputs))

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
            self._replay_as_trajectory(arm, traj)

    def _replay_as_trajectory(self, arm: ArmSpec, traj) -> None:
        """ros2_control 의 JointTrajectoryController 로 한 번에 전송."""
        msg = build_joint_trajectory(traj, arm.controller_joint_names)
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
