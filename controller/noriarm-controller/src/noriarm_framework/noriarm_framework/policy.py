"""정책 인터페이스.

게임 진행 로직 (rule_based / smolVLA 모방학습 / 그 외) 을 추상화해 게임 루프 코드는
어떤 정책이든 같은 방식으로 호출할 수 있게 한다.

게임 루프:
    obs = sense()
    action = policy.step(obs)
    apply(action)

`Observation` 은 게임마다 들어오는 신호가 다르므로 optional 필드로 폭넓게 잡는다 —
rule_based 가 marker_position 만 쓰고, smolVLA 가 images + state 를 쓰고, 그 외
정책이 자기 필드를 읽는 식으로 정책 측이 필요한 것만 골라 본다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class GameContext:
    """policy.reset() 으로 전달되는 게임 세션 정보."""

    game_name: str
    target: Literal["sim", "real"]
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    """한 timestep 의 관측값.

    필드는 모두 optional — 정책이 필요한 것만 사용한다.
        images        — 카메라 id → BGR ndarray (H, W, 3)
        joint_states  — arm id → joint position ndarray (radian)
        hand_position — vision 노드가 검출한 손 위치/선택 (예: 'O' / 'X' / (x, y))
        lang_prompt   — smolVLA 같은 언어조건 정책의 텍스트 프롬프트
        timestamp     — 관측 시각 (s, monotonic 또는 ROS 시각)
        extra         — 게임 고유 신호용 자유 dict
    """

    images: dict[str, np.ndarray] | None = None
    joint_states: dict[str, np.ndarray] | None = None
    hand_position: tuple[float, float] | str | None = None
    lang_prompt: str | None = None
    timestamp: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


# --- Action — 정책이 돌려주는 명령. union 으로 표현. ----------------------


@dataclass(frozen=True)
class IdleAction:
    """아무것도 하지 말라."""

    kind: Literal["idle"] = "idle"


@dataclass(frozen=True)
class ReplayTrajectoryAction:
    """사전 녹화 trajectory 파일을 재생하라."""

    name: str  # game.yaml 또는 정책이 알고 있는 trajectory 식별자
    kind: Literal["replay_trajectory"] = "replay_trajectory"


@dataclass(frozen=True)
class JointTargetsAction:
    """ros2_control 의 JointTrajectoryController 로 보낼 절대 joint 목표."""

    arm_id: str
    joint_names: tuple[str, ...]
    positions: np.ndarray  # shape: (N,) — radian
    duration_s: float = 1.0
    kind: Literal["joint_targets"] = "joint_targets"


@dataclass(frozen=True)
class MultiArmJointTargetsAction:
    """양팔(또는 N팔) 동시 절대 joint 목표.

    bimanual SmolVLA/ACT 처럼 한 추론 step 의 출력이 여러 팔의 joint 차원을 합쳐서
    들어오는 경우, 단일 timestep 에 모든 팔로 분할 publish 하기 위해 사용.
    `_apply` 가 per_arm 의 각 항목을 해당 arm 의 publisher 로 전달.
    """

    per_arm: tuple[JointTargetsAction, ...]
    duration_s: float = 1.0
    kind: Literal["multi_arm_joint_targets"] = "multi_arm_joint_targets"


Action = (
    IdleAction
    | ReplayTrajectoryAction
    | JointTargetsAction
    | MultiArmJointTargetsAction
)


# 편의 생성자 — 정책 코드가 짧아진다.
class _ActionFactory:
    @staticmethod
    def idle() -> IdleAction:
        return IdleAction()

    @staticmethod
    def replay_trajectory(name: str) -> ReplayTrajectoryAction:
        return ReplayTrajectoryAction(name=name)

    @staticmethod
    def joint_targets(
        arm_id: str,
        joint_names: tuple[str, ...] | list[str],
        positions: np.ndarray,
        duration_s: float = 1.0,
    ) -> JointTargetsAction:
        return JointTargetsAction(
            arm_id=arm_id,
            joint_names=tuple(joint_names),
            positions=np.asarray(positions, dtype=np.float64),
            duration_s=duration_s,
        )

    @staticmethod
    def multi_arm_joint_targets(
        per_arm: list[JointTargetsAction] | tuple[JointTargetsAction, ...],
        duration_s: float = 1.0,
    ) -> MultiArmJointTargetsAction:
        return MultiArmJointTargetsAction(
            per_arm=tuple(per_arm),
            duration_s=duration_s,
        )


Actions = _ActionFactory()


# --- Policy Protocol ------------------------------------------------------


@runtime_checkable
class Policy(Protocol):
    """게임 정책 인터페이스 — rule_based / smolvla / 기타 모두 이걸 구현한다."""

    def reset(self, ctx: GameContext) -> None: ...

    def step(self, obs: Observation) -> Action: ...
