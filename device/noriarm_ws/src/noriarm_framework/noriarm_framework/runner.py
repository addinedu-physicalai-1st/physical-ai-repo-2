"""게임 실행 진입점.

ROS2 (`rclpy`, `trajectory_msgs`) 의존성은 `_ros_runner` 모듈로 분리해 lazy import 한다 —
list / validate CLI 서브커맨드는 ROS 환경 source 없이도 돌도록.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from noriarm_framework.manifest import GameConfig


@dataclass
class RunnerConfig:
    config: GameConfig
    target: Literal["sim", "real"]
    inputs: dict[str, Any] = field(default_factory=dict)  # --input KEY=VAL
    max_steps: int | None = None
    # Gazebo + ros2_control 의 arm_controller spawn 은 보통 20~40s 걸려서 sim 은 넉넉히.
    # real 은 이미 떠 있다고 가정하므로 짧게.
    wait_subscriber_timeout_s: float | None = None

    def effective_subscriber_timeout(self) -> float:
        if self.wait_subscriber_timeout_s is not None:
            return self.wait_subscriber_timeout_s
        return 60.0 if self.target == "sim" else 10.0


def run(cfg: RunnerConfig) -> None:
    """CLI 진입점. rclpy 라이프사이클 + Gazebo lifecycle 까지 책임진다."""
    # rclpy 가 필요한 시점에만 로드 — 환경 source 안 되어 있어도 list/validate 는 돌도록.
    from noriarm_framework._ros_runner import run_with_ros

    run_with_ros(cfg)
