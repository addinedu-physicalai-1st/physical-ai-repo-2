"""block_stacking/game.yaml 이 매니페스트 로더로 정상 파싱되는지."""
from __future__ import annotations

from importlib import resources

from noriarm_framework.manifest import load_manifest


def test_load_block_stacking_game_yaml() -> None:
    with resources.path(
        "noriarm_framework.games.block_stacking", "game.yaml"
    ) as p:
        config = load_manifest(p)
    assert config.name == "block_stacking"
    assert config.display == "블럭쌓기"
    assert config.policy.kind == "act"
    assert config.policy.extra["repo_id"] == "jisoo3/act_game_block_stacking_0521"
    assert len(config.arms) == 1


def test_block_stacking_repo_id_matches_game_yaml() -> None:
    from noriarm_framework.games.block_stacking import (
        block_stacking_repo_id,
        load_block_stacking_config,
    )
    assert block_stacking_repo_id() == "jisoo3/act_game_block_stacking_0521"
    # 같은 호출은 cache 로 동일 객체 반환.
    assert load_block_stacking_config() is load_block_stacking_config()
