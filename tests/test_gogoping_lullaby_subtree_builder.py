"""BT_lullaby_sub 빌더 단위 테스트.

- 빌더 리턴이 LullabyAudio 인스턴스
- 이름이 'BT_lullaby_sub' (tree_inspector._find_subtree 의 BT_*_sub 패턴 매칭)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.behaviors.lullaby.lullaby_audio import LullabyAudio  # noqa: E402
from gogoping_modes.bt.trees.sub_trees.BT_lullaby_sub import build_lullaby_subtree  # noqa: E402


def _ctx():
    ctx = MagicMock()
    ctx.ui = MagicMock()
    return ctx


def test_build_returns_lullaby_audio_instance():
    """빌더 = LullabyAudio 단일 leaf."""
    root = build_lullaby_subtree(_ctx())
    assert isinstance(root, LullabyAudio)


def test_build_returns_node_with_bt_lullaby_sub_name():
    """tree_inspector 의 BT_*_sub 패턴 매칭 위해 이름이 정확히 'BT_lullaby_sub'."""
    root = build_lullaby_subtree(_ctx())
    assert root.name == "BT_lullaby_sub"
