"""OX 퀴즈 — rule-based 정책 스켈레톤.

지금은 답(`obs.extra["answer"]`) → trajectory 파일 1:1 매핑만 한다. 후속 SR 에서:
  - 손 검출 (mediapipe) 로 obs.marker_position 채우기 → 정답 판정 + 점수
  - episode 종료 조건 (정답 후 N 초)
"""
from __future__ import annotations

from typing import Literal

from noriarm_framework.manifest import GameConfig
from noriarm_framework.policy import (
    Action,
    Actions,
    GameContext,
    Observation,
    Policy,
)


class OXRulePolicy(Policy):
    def __init__(self, trajectory_map: dict[str, str]) -> None:
        # answer (O / X) → trajectory 식별자.
        self._trajectory_map = trajectory_map
        self._fired = False

    def reset(self, ctx: GameContext) -> None:
        self._fired = False

    def step(self, obs: Observation) -> Action:
        if self._fired:
            return Actions.idle()
        answer = obs.extra.get("answer") if obs.extra else None
        if not isinstance(answer, str) or answer not in self._trajectory_map:
            return Actions.idle()
        self._fired = True
        return Actions.replay_trajectory(self._trajectory_map[answer])


def build_policy(config: GameConfig) -> Policy:
    """Runner 가 호출하는 진입점 — 매니페스트의 policy.extra 에서 옵션을 꺼낸다."""
    raw = config.policy.extra.get("trajectory_map") or {}
    if not isinstance(raw, dict) or not raw:
        raise RuntimeError(
            "ox_quiz policy_rule: matching 'trajectory_map' 이 비었습니다 (game.yaml 확인)"
        )
    trajectory_map = {str(k): str(v) for k, v in raw.items()}
    return OXRulePolicy(trajectory_map=trajectory_map)


# 정책 진입점만 외부에 노출.
__all__ = ["OXRulePolicy", "build_policy"]


# Python 3.11 의 type union 기재용 (lint 호환성).
_Answer = Literal["O", "X"]
