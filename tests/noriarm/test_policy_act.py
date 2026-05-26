"""ACT 정책 어댑터 — lerobot 미설치 환경에서도 import 가능, step 호출 시 lazy load."""
from __future__ import annotations

import importlib.util

import numpy as np
import pytest

from noriarm_framework.games.block_stacking.policy_act import (
    ACTPolicyAdapter,
    build_policy,
)
from noriarm_framework.manifest import GameConfig, PolicyConfig, RuntimeConfig
from noriarm_framework.policy import (
    GameContext,
    IdleAction,
    JointTargetsAction,
    Observation,
)


HAS_LEROBOT = importlib.util.find_spec("lerobot") is not None


def _ctx() -> GameContext:
    return GameContext(game_name="block_stacking", target="sim")


def test_adapter_import_does_not_require_lerobot() -> None:
    """단순 import 는 lerobot 없이도 동작해야 한다 (테스트 환경 호환성)."""
    ACTPolicyAdapter  # noqa: B018


def test_step_is_idle_when_not_ready() -> None:
    adapter = ACTPolicyAdapter(
        repo_id="jisoo3/act_game_block_stacking_0521",
        joint_names=("joint1", "joint2", "joint3", "joint4", "joint5"),
    )
    adapter.reset(_ctx())
    # load_policy_async 가 호출되지 않은 상태 → idle.
    assert isinstance(adapter.step(Observation()), IdleAction)


def test_build_policy_from_manifest() -> None:
    config = GameConfig(
        name="block_stacking",
        display="블럭쌓기",
        cameras=(),
        arms=(),
        policy=PolicyConfig(
            kind="act",
            module="noriarm_framework.games.block_stacking.policy_act",
            extra={
                "repo_id": "jisoo3/act_game_block_stacking_0521",
                "joint_names": ["joint1", "joint2", "joint3", "joint4", "joint5"],
            },
        ),
        runtime=RuntimeConfig(),
    )
    policy = build_policy(config)
    assert isinstance(policy, ACTPolicyAdapter)


@pytest.mark.skipif(not HAS_LEROBOT, reason="lerobot 미설치")
def test_load_and_step_when_lerobot_available() -> None:
    """lerobot 이 있는 환경에서 load_policy() 호출 + 더미 obs 로 1 step.

    jisoo3/act_game_block_stacking_0521 모델 스펙:
      - image_features: observation.images.front (3,480,640), observation.images.wrist (3,480,640)
      - action shape: (6,)
    camera_keys 는 obs.images 키와 모델의 feature 키를 동시에 결정한다.
    """
    adapter = ACTPolicyAdapter(
        repo_id="jisoo3/act_game_block_stacking_0521",
        joint_names=("joint1", "joint2", "joint3", "joint4", "joint5", "joint6"),
        camera_keys=("front", "wrist"),
    )
    adapter.reset(_ctx())
    # 모델이 실제로 받아지면 step 결과는 JointTargetsAction.
    adapter.load_policy_blocking()
    obs = Observation(
        images={
            "front": np.zeros((480, 640, 3), dtype=np.uint8),
            "wrist": np.zeros((480, 640, 3), dtype=np.uint8),
        },
        joint_states={"pointer": np.zeros(6, dtype=np.float64)},
    )
    action = adapter.step(obs)
    assert isinstance(action, JointTargetsAction)
    assert action.positions.shape == (6,)
