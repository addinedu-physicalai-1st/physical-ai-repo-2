#!/usr/bin/env python3
"""NoriArm 부트스트랩 — 블럭쌓기 ACT 체크포인트가 HF cache 에 있는지 확인하고,
없으면 다운로드.

ui-robot.sh noriarm 이 호출. 다운로드 진행률은 huggingface_hub 가 stdout 으로 출력.

repo_id 는 `controller/.../games/block_stacking/game.yaml` 의 policy.repo_id 한
곳을 단일 진실원으로 읽는다. 이 스크립트는 ROS 환경 source 전에 돌 수 있어야 하므로
noriarm_framework import 에 의존하지 않고 yaml 파일을 파일시스템에서 직접 파싱.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import yaml
from huggingface_hub import snapshot_download

logger = logging.getLogger("noriarm_check_models")

# 단일 진실원 — block_stacking 의 game.yaml.
REPO_ROOT = Path(__file__).resolve().parent.parent
GAME_YAML_PATH = (
    REPO_ROOT
    / "controller/noriarm-controller/src/noriarm_framework/noriarm_framework"
    / "games/block_stacking/game.yaml"
)


def resolve_repo_id(*, yaml_path: Path | None = None) -> str:
    """game.yaml 의 policy.repo_id 추출. yaml 형식 변경 시 여기와 manifest 로더만 갱신."""
    p = yaml_path or GAME_YAML_PATH
    with p.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    policy = (data or {}).get("policy") or {}
    repo_id = policy.get("repo_id")
    if not repo_id:
        raise RuntimeError(f"{p}: policy.repo_id 누락")
    return str(repo_id)


def _default_cache_root() -> Path:
    # HF 의 기본 캐시 경로 — 환경변수 우선.
    env = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "huggingface" / "hub"


def is_cached(repo_id: str, *, cache_root: Path | None = None) -> bool:
    """`<cache_root>/models--<org>--<name>/snapshots/<sha>/<files>` 존재 여부.

    snapshot 디렉토리 안에 파일이 하나라도 있어야 진짜로 받아진 것으로 본다 —
    중단된 다운로드는 빈 snapshot 만 남길 수 있어 그것까지 cache hit 으로 잘못 잡지 않도록.
    """
    root = cache_root or _default_cache_root()
    repo_dir = root / f"models--{repo_id.replace('/', '--')}" / "snapshots"
    if not repo_dir.is_dir():
        return False
    for snap in repo_dir.iterdir():
        if snap.is_dir() and any(snap.iterdir()):
            return True
    return False


def ensure(repo_id: str, *, cache_root: Path | None = None) -> Path:
    """캐시에 없으면 snapshot_download, 있으면 그대로. 다운로드 디렉토리 경로 반환."""
    if is_cached(repo_id, cache_root=cache_root):
        logger.info("이미 캐시에 있음: %s", repo_id)
        return _default_cache_root()
    logger.info("HF 다운로드 시작: %s", repo_id)
    path = snapshot_download(repo_id=repo_id, cache_dir=str(cache_root) if cache_root else None)
    logger.info("다운로드 완료: %s", path)
    return Path(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NoriArm 부트스트랩 모델 점검")
    parser.add_argument(
        "--repo-id",
        default=None,
        help="명시적 HF repo override (기본: game.yaml 의 policy.repo_id)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="[noriarm-models] %(message)s")
    try:
        repo_id = args.repo_id or resolve_repo_id()
        logger.info("repo_id=%s (source=%s)", repo_id, "cli" if args.repo_id else GAME_YAML_PATH)
        ensure(repo_id)
        return 0
    except Exception as e:  # noqa: BLE001
        logger.error("모델 점검 실패: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
