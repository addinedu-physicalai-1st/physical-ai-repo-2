"""scripts/noriarm_check_models.py — HF snapshot 존재 점검 + 다운로드 트리거."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import noriarm_check_models as ncm  # noqa: E402


def test_resolve_repo_id_from_game_yaml() -> None:
    """game.yaml 의 policy.repo_id 가 단일 진실원."""
    assert ncm.resolve_repo_id() == "jisoo3/act_game_block_stacking_0521"


def test_is_cached_returns_true_when_snapshot_exists(tmp_path: Path) -> None:
    repo_id = "jisoo3/act_game_block_stacking_0521"
    cache_root = tmp_path / "hub"
    repo_dir = cache_root / f"models--{repo_id.replace('/', '--')}" / "snapshots" / "abc123"
    repo_dir.mkdir(parents=True)
    (repo_dir / "config.json").write_text("{}")
    assert ncm.is_cached(repo_id, cache_root=cache_root)


def test_is_cached_returns_false_when_no_snapshot(tmp_path: Path) -> None:
    assert not ncm.is_cached("foo/bar", cache_root=tmp_path)


def test_ensure_calls_snapshot_download_when_not_cached(tmp_path: Path) -> None:
    with patch.object(ncm, "snapshot_download") as mock_dl:
        mock_dl.return_value = str(tmp_path / "snap")
        ncm.ensure("foo/bar", cache_root=tmp_path)
        mock_dl.assert_called_once()
        kwargs = mock_dl.call_args.kwargs
        assert kwargs["repo_id"] == "foo/bar"


def test_ensure_skips_download_when_cached(tmp_path: Path) -> None:
    repo_id = "foo/bar"
    repo_dir = tmp_path / f"models--{repo_id.replace('/', '--')}" / "snapshots" / "x"
    repo_dir.mkdir(parents=True)
    (repo_dir / "config.json").write_text("{}")
    with patch.object(ncm, "snapshot_download") as mock_dl:
        ncm.ensure(repo_id, cache_root=tmp_path)
        mock_dl.assert_not_called()
