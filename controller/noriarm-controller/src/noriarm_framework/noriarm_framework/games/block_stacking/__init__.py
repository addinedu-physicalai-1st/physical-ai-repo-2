"""NoriArm 블럭쌓기 게임 — ACT 정책 + RPS 선공 + 홈 복귀 감지.

`game.yaml` 의 단일 진실원에서 GameConfig 를 로드해 노출한다 — repo_id, joint_names
등을 코드에 hardcoding 하지 않기 위함. 호출자 (Control Server 라우터·테스트) 는
`load_block_stacking_config()` 로 같은 인스턴스를 반복 사용.
"""
from __future__ import annotations

from functools import lru_cache
from importlib import resources

from noriarm_framework.manifest import GameConfig, load_manifest


@lru_cache(maxsize=1)
def load_block_stacking_config() -> GameConfig:
    """game.yaml 을 1 회 로드 후 캐시. 같은 프로세스 내 호출은 동일 객체 반환."""
    with resources.path(__name__, "game.yaml") as p:
        return load_manifest(p)


def block_stacking_repo_id() -> str:
    """블럭쌓기 ACT 체크포인트의 HF repo id (game.yaml 의 policy.repo_id)."""
    cfg = load_block_stacking_config()
    repo_id = cfg.policy.extra.get("repo_id")
    if not repo_id:
        raise RuntimeError(
            "block_stacking/game.yaml 의 policy.repo_id 누락 — 매니페스트 확인"
        )
    return str(repo_id)


__all__ = ["load_block_stacking_config", "block_stacking_repo_id"]
