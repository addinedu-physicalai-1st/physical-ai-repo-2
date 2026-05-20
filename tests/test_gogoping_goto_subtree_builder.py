"""BT_goto_sub 빌더 단위 테스트.

- 빌더 리턴이 Sequence(memory=True)
- 자식 2개 = NavigateToVertex + UIPublish
- UIPublish 의 message dict 가 도착 알림과 정확히 일치
- 이름이 'BT_goto_sub' (tree_inspector 의 BT_*_sub 패턴 매칭)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import py_trees

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.behaviors.common.ui_publish import UIPublish  # noqa: E402
from gogoping_modes.bt.behaviors.navigation.navigate_to_vertex import NavigateToVertex  # noqa: E402
from gogoping_modes.bt.trees.sub_trees.BT_goto_sub import (  # noqa: E402
    _ARRIVAL_MSG,
    build_goto_subtree,
)


def _ctx():
    ctx = MagicMock()
    ctx.ui = MagicMock()
    return ctx


def test_builder_returns_sequence_with_correct_name():
    root = build_goto_subtree(_ctx())
    assert isinstance(root, py_trees.composites.Sequence)
    assert root.name == "BT_goto_sub"


def test_builder_has_two_children_navigate_then_uipublish():
    root = build_goto_subtree(_ctx())
    assert len(root.children) == 2
    assert isinstance(root.children[0], NavigateToVertex)
    assert isinstance(root.children[1], UIPublish)


def test_uipublish_message_is_announce_arrival():
    root = build_goto_subtree(_ctx())
    ui = root.children[1]
    assert ui._message == {"event": "announce", "text": "도착했습니다"}


def test_arrival_msg_constant_matches():
    assert _ARRIVAL_MSG == {"event": "announce", "text": "도착했습니다"}
