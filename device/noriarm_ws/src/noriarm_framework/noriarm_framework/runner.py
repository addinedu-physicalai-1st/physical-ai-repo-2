"""게임 루프 스켈레톤.

매니페스트와 정책 인스턴스를 받아 sense → step → apply 루프를 돈다. 이 시점의 구현은
스캐폴드 — sensing 과 actuation 은 ROS2 통합이 추가될 때 채워진다 (SR-NORI-005 참조).
지금은:
    - reset/step 호출 흐름과 종료 조건만 검증
    - apply() 는 Action 종류만 로그로 찍는 더미

후속 SR 에서 sensing (카메라 토픽 구독, 마커 검출) / actuation (trajectory publish) 을
실제 ROS2 노드로 채운다.
"""
from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass
from typing import Literal

from noriarm_framework.manifest import GameConfig
from noriarm_framework.policy import (
    Action,
    GameContext,
    IdleAction,
    JointTargetsAction,
    Observation,
    Policy,
    ReplayTrajectoryAction,
)

logger = logging.getLogger(__name__)


@dataclass
class RunnerConfig:
    config: GameConfig
    target: Literal["sim", "real"]
    max_steps: int | None = None  # None 이면 episode_timeout_s 만큼만 돈다


def load_policy(config: GameConfig) -> Policy:
    """매니페스트의 policy.module 을 동적 import 해 Policy 인스턴스를 만든다.

    convention — 모듈 안에 `build_policy(config: GameConfig) -> Policy` 가 있어야 한다.
    """
    module = importlib.import_module(config.policy.module)
    if not hasattr(module, "build_policy"):
        raise RuntimeError(
            f"{config.policy.module}: build_policy(config) 함수가 없습니다"
        )
    policy: Policy = module.build_policy(config)
    if not isinstance(policy, Policy):
        raise RuntimeError(
            f"{config.policy.module}.build_policy() 가 Policy 프로토콜을 만족하지 않습니다"
        )
    return policy


def run(cfg: RunnerConfig) -> None:
    policy = load_policy(cfg.config)
    ctx = GameContext(game_name=cfg.config.name, target=cfg.target)
    policy.reset(ctx)

    logger.info(
        "starting game loop: name=%s target=%s rate_hz=%.1f",
        cfg.config.name,
        cfg.target,
        cfg.config.runtime.rate_hz,
    )

    period = 1.0 / cfg.config.runtime.rate_hz
    deadline = time.monotonic() + cfg.config.runtime.episode_timeout_s
    step = 0
    while time.monotonic() < deadline:
        if cfg.max_steps is not None and step >= cfg.max_steps:
            break
        obs = _sense_stub(step)
        action = policy.step(obs)
        _apply_stub(action)
        step += 1
        time.sleep(period)

    logger.info("game loop finished: steps=%d", step)


def _sense_stub(step: int) -> Observation:
    """sensing 스텁 — 후속 SR 에서 ROS2 카메라/joint_states 구독으로 교체."""
    return Observation(timestamp=float(step))


def _apply_stub(action: Action) -> None:
    """actuation 스텁 — 후속 SR 에서 ROS2 publisher 로 교체."""
    if isinstance(action, IdleAction):
        logger.debug("apply: idle")
    elif isinstance(action, ReplayTrajectoryAction):
        logger.info("apply: replay_trajectory name=%s", action.name)
    elif isinstance(action, JointTargetsAction):
        logger.info(
            "apply: joint_targets arm=%s joints=%s duration=%.2fs",
            action.arm_id,
            action.joint_names,
            action.duration_s,
        )
    else:
        logger.warning("apply: unknown action %r", action)
