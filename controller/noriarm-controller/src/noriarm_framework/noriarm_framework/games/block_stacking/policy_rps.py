"""가위바위보 '보' 단발 replay 정책.

블럭쌓기 진입 후 RPS 단계에서 1 회만 호출돼 사전 녹화한 '보' trajectory 재생을
트리거한다. 데모 단순화를 위해 결과 판정 (사람 가위 → 사람 승) 은 UI 측에서 고정값
으로 처리하고 정책은 단순히 '보' trajectory 만 재생한다.
"""
from __future__ import annotations

from noriarm_framework.manifest import GameConfig
from noriarm_framework.policy import (
    Action,
    Actions,
    GameContext,
    Observation,
    Policy,
)

_DEFAULT_TRAJECTORY = "rps_paper_trajectory.json"


class RPSPaperPolicy(Policy):
    def __init__(self, *, trajectory_name: str = _DEFAULT_TRAJECTORY) -> None:
        self._trajectory_name = trajectory_name
        self._fired = False

    def reset(self, ctx: GameContext) -> None:
        self._fired = False

    def step(self, obs: Observation) -> Action:
        if self._fired:
            return Actions.idle()
        self._fired = True
        return Actions.replay_trajectory(self._trajectory_name)


def build_policy(config: GameConfig) -> Policy:
    name = str(config.policy.extra.get("trajectory_name") or _DEFAULT_TRAJECTORY)
    return RPSPaperPolicy(trajectory_name=name)


__all__ = ["RPSPaperPolicy", "build_policy"]
