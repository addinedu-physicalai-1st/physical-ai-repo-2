"""RPS '보' 단발 replay 정책."""
from __future__ import annotations

from noriarm_framework.games.block_stacking.policy_rps import RPSPaperPolicy, build_policy
from noriarm_framework.manifest import GameConfig, PolicyConfig, RuntimeConfig
from noriarm_framework.policy import (
    GameContext,
    IdleAction,
    Observation,
    ReplayTrajectoryAction,
)


def _ctx() -> GameContext:
    return GameContext(game_name="block_stacking", target="sim")


def test_step_returns_replay_action_once() -> None:
    policy = RPSPaperPolicy(trajectory_name="rps_paper_trajectory.json")
    policy.reset(_ctx())
    action = policy.step(Observation())
    assert isinstance(action, ReplayTrajectoryAction)
    assert action.name == "rps_paper_trajectory.json"


def test_step_is_idle_after_fired() -> None:
    policy = RPSPaperPolicy(trajectory_name="rps_paper_trajectory.json")
    policy.reset(_ctx())
    policy.step(Observation())  # consume the replay
    assert isinstance(policy.step(Observation()), IdleAction)


def test_build_policy_from_manifest() -> None:
    config = GameConfig(
        name="block_stacking",
        display="블럭쌓기",
        cameras=(),
        arms=(),
        policy=PolicyConfig(
            kind="rule_based",
            module="noriarm_framework.games.block_stacking.policy_rps",
            extra={"trajectory_name": "rps_paper_trajectory.json"},
        ),
        runtime=RuntimeConfig(),
    )
    policy = build_policy(config)
    policy.reset(_ctx())
    assert isinstance(policy.step(Observation()), ReplayTrajectoryAction)
