"""snapshot() 의 main/sub 분리 — main 은 SubTree 경계에서 멈추고, 상세는 sub 블록에만.

버그: _flatten_leaves 가 BT_*_sub 내부까지 재귀 → SubTree 상세(숨바꼭질 patrol route 등)가
main_tree.children 로 샘 + sub 와 중복. main 은 monitors + BT_*_sub 1줄만 나와야 한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import py_trees
from py_trees.common import ParallelPolicy

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.tree_inspector import snapshot  # noqa: E402


def _build_tree_with_subtree():
    """Parallel[ Monitor, BT_demo_sub[ step_a, BT_patrol_sub[ route_1, route_2 ] ] ] (모두 RUNNING)."""
    route = py_trees.composites.Parallel(
        name="BT_patrol_sub",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            py_trees.behaviours.Running(name="route_1"),
            py_trees.behaviours.Running(name="route_2"),
        ],
    )
    sub = py_trees.composites.Sequence(
        name="BT_demo_sub", memory=True,
        children=[py_trees.behaviours.Running(name="step_a"), route],
    )
    root = py_trees.composites.Parallel(
        name="MainTree[DEMO]",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[py_trees.behaviours.Running(name="SomeMonitor"), sub],
    )
    root.tick_once()
    return root


def test_main_stops_at_subtree_boundary():
    """main_tree.children = [Monitor, BT_demo_sub] — subtree 내부 leaf 안 샘."""
    snap = snapshot(fsm_state="DEMO", root_tree=_build_tree_with_subtree())
    names = [c["name"] for c in snap["main_tree"]["children"]]
    assert names == ["SomeMonitor", "BT_demo_sub"]
    assert "step_a" not in names
    assert "route_1" not in names and "route_2" not in names


def test_sub_block_shows_full_detail():
    """sub_tree 는 상세 전부 — 중첩 BT_patrol_sub 의 route 까지 포함."""
    snap = snapshot(fsm_state="DEMO", root_tree=_build_tree_with_subtree())
    assert snap["sub_tree"]["name"] == "BT_demo_sub"
    sub_names = [c["name"] for c in snap["sub_tree"]["children"]]
    assert "step_a" in sub_names
    assert "route_1" in sub_names and "route_2" in sub_names
