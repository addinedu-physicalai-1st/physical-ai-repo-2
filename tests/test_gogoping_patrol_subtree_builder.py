"""BT_patrol_sub 빌더 단위 테스트.

- root: Sequence(memory=True), name='BT_patrol_sub'
- 자식 = vertex 수만큼 FailureIsSuccess(Sequence(visit_<name>, [Select, Nav, Sweep]))
- 빈 / 잘못된 waypoints reject
- 자식 순서가 입력 순서와 일치
- 각 visit 의 SelectVertex 가 올바른 vertex_name 보유
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import py_trees
import pytest
from py_trees.decorators import FailureIsSuccess

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.behaviors.common.select_vertex import SelectVertex  # noqa: E402
from gogoping_modes.bt.behaviors.common.set_patrol_index import SetPatrolIndex  # noqa: E402
from gogoping_modes.bt.behaviors.follow.pan_camera_sweep import PanCameraSweep  # noqa: E402
from gogoping_modes.bt.behaviors.navigation.brake_and_wait import BrakeAndWait  # noqa: E402
from gogoping_modes.bt.behaviors.navigation.navigate_to_vertex import NavigateToVertex  # noqa: E402
from gogoping_modes.bt.trees.sub_trees.BT_patrol_sub import build_patrol_sub  # noqa: E402


def _ctx():
    ctx = MagicMock()
    ctx.camera_pan = MagicMock()
    ctx.node = MagicMock()
    return ctx


def setup_function():
    py_trees.blackboard.Blackboard.clear()


def test_builder_returns_sequence_with_correct_name():
    root = build_patrol_sub(_ctx(), ["A", "B", "C"])
    assert isinstance(root, py_trees.composites.Sequence)
    assert root.name == "BT_patrol_sub"


def test_builder_creates_one_visit_per_waypoint_plus_done_marker():
    """root.children: visit N 개 (FailureIsSuccess) + SetPatrolIndex(done) 1 개."""
    root = build_patrol_sub(_ctx(), ["A", "B", "C"])
    assert len(root.children) == 4   # 3 visits + 1 done marker
    for child in root.children[:-1]:
        assert isinstance(child, FailureIsSuccess)
    assert isinstance(root.children[-1], SetPatrolIndex)


def test_done_marker_has_index_n():
    """마지막 SetPatrolIndex 의 인덱스 = len(waypoints)."""
    root = build_patrol_sub(_ctx(), ["A", "B", "C"])
    assert root.children[-1]._index == 3


def test_each_visit_has_setindex_select_nav_brake_sweep_in_order():
    root = build_patrol_sub(_ctx(), ["A", "B"])
    for safe_visit in root.children[:-1]:  # done marker 제외
        visit = safe_visit.children[0]   # FailureIsSuccess wraps a single child Sequence
        assert isinstance(visit, py_trees.composites.Sequence)
        assert visit.name.startswith("visit_")
        # 자식 5개 — set_index / select / nav / brake / sweep
        assert len(visit.children) == 5
        assert isinstance(visit.children[0], SetPatrolIndex)
        assert isinstance(visit.children[1], SelectVertex)
        assert isinstance(visit.children[2], NavigateToVertex)
        assert isinstance(visit.children[3], BrakeAndWait)
        assert isinstance(visit.children[4], PanCameraSweep)


def test_set_index_values_match_visit_order():
    """visit_i 의 첫 자식 SetPatrolIndex 의 index 가 i 와 일치."""
    waypoints = ["A", "B", "C", "D"]
    root = build_patrol_sub(_ctx(), waypoints)
    for i, safe_visit in enumerate(root.children[:-1]):
        visit = safe_visit.children[0]
        set_idx = visit.children[0]
        assert isinstance(set_idx, SetPatrolIndex)
        assert set_idx._index == i


def test_select_vertex_names_match_input_order():
    waypoints = ["교실A", "운동장", "복도1"]
    root = build_patrol_sub(_ctx(), waypoints)
    for i, safe_visit in enumerate(root.children[:-1]):
        visit = safe_visit.children[0]
        sel = visit.children[1]
        assert isinstance(sel, SelectVertex)
        assert sel._vertex_name == waypoints[i]


def test_single_waypoint_ok():
    root = build_patrol_sub(_ctx(), ["solo"])
    # 1 visit + 1 done marker
    assert len(root.children) == 2


def test_empty_waypoints_rejected():
    with pytest.raises(ValueError):
        build_patrol_sub(_ctx(), [])


def test_empty_name_in_list_rejected():
    with pytest.raises(ValueError):
        build_patrol_sub(_ctx(), ["A", "", "C"])


def test_visit_names_include_vertex():
    """admin UI tree_inspector 에서 vertex 별 visit 식별 가능하게 — name 에 vertex 포함."""
    root = build_patrol_sub(_ctx(), ["foo"])
    safe = root.children[0]   # 첫 visit
    assert "foo" in safe.name
    visit = safe.children[0]
    assert visit.name == "visit_foo"
    assert visit.children[0].name == "set_index_0"
    assert visit.children[1].name == "select_foo"
    assert visit.children[2].name == "nav_foo"
    assert visit.children[3].name == "brake_foo"
    assert visit.children[4].name == "sweep_foo"


def test_memory_true_on_sequences():
    """Sequence(memory=True) — 한 자식 SUCCESS 후 다음 자식 진입."""
    root = build_patrol_sub(_ctx(), ["A", "B"])
    assert root.memory is True
    for safe_visit in root.children[:-1]:
        visit = safe_visit.children[0]
        assert visit.memory is True
