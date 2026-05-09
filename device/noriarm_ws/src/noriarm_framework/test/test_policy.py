"""Policy 인터페이스 + OX rule policy 스켈레톤 단위 테스트."""
from __future__ import annotations

from pathlib import Path

import pytest

from noriarm_framework.games.ox_quiz.policy_rule import OXRulePolicy, build_policy
from noriarm_framework.manifest import load_manifest
from noriarm_framework.policy import (
    Action,
    GameContext,
    IdleAction,
    Observation,
    Policy,
    ReplayTrajectoryAction,
)


REPO_GAMES = (
    Path(__file__).resolve().parents[1]
    / "noriarm_framework"
    / "games"
    / "ox_quiz"
    / "game.yaml"
)


def _ctx() -> GameContext:
    return GameContext(game_name="ox_quiz", target="sim")


def test_policy_protocol_is_satisfied() -> None:
    policy = OXRulePolicy(trajectory_map={"O": "ep0", "X": "ep1"})
    assert isinstance(policy, Policy)


def test_idle_when_no_answer_in_obs() -> None:
    policy = OXRulePolicy(trajectory_map={"O": "ep0", "X": "ep1"})
    policy.reset(_ctx())
    action = policy.step(Observation())
    assert isinstance(action, IdleAction)


def test_replay_on_first_answer_then_idle() -> None:
    policy = OXRulePolicy(trajectory_map={"O": "ep0", "X": "ep1"})
    policy.reset(_ctx())

    first = policy.step(Observation(extra={"answer": "O"}))
    assert isinstance(first, ReplayTrajectoryAction)
    assert first.name == "ep0"

    # 같은 episode 안에서는 한 번만 발사.
    second = policy.step(Observation(extra={"answer": "O"}))
    assert isinstance(second, IdleAction)

    # reset 후에는 다시 발사 가능.
    policy.reset(_ctx())
    third = policy.step(Observation(extra={"answer": "X"}))
    assert isinstance(third, ReplayTrajectoryAction)
    assert third.name == "ep1"


@pytest.mark.skipif(not REPO_GAMES.is_file(), reason="ox_quiz game.yaml 미생성")
def test_build_policy_from_repo_manifest() -> None:
    cfg = load_manifest(REPO_GAMES)
    policy = build_policy(cfg)
    assert isinstance(policy, Policy)
    policy.reset(_ctx())
    action: Action = policy.step(Observation(extra={"answer": "O"}))
    assert isinstance(action, ReplayTrajectoryAction)
