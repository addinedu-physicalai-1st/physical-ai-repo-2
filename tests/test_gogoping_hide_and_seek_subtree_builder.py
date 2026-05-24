"""BT_hide_and_seek_sub 빌더 단위 테스트.

빌더는 blackboard 의 ``search_waypoints`` 를 읽어:
- 비어있지 않으면 → ``build_patrol_sub(ctx, wps)`` 결과 (Sequence "BT_patrol_sub") 반환
- 비어있으면 / 미설정이면 → ``Failure`` leaf 반환

정상 경로에선 reconciler 가 빈 리스트를 미리 차단하지만, ForceState 디버그 우회
시나리오 방어를 위해 빌더 자체도 깨지지 않아야 한다.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import py_trees
from py_trees.common import Access

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.blackboard import Keys  # noqa: E402
from gogoping_modes.bt.trees.sub_trees.BT_hide_and_seek_sub import build_hide_and_seek_sub  # noqa: E402


def _ctx():
    ctx = MagicMock()
    ctx.camera_pan = MagicMock()
    ctx.node = MagicMock()
    return ctx


def setup_function():
    py_trees.blackboard.Blackboard.clear()


def _set_search_waypoints(wps):
    bb = py_trees.blackboard.Client(name="test_setup")
    bb.register_key(key=Keys.SEARCH_WAYPOINTS, access=Access.WRITE)
    bb.set(Keys.SEARCH_WAYPOINTS, wps)


def test_returns_patrol_sub_when_waypoints_present():
    _set_search_waypoints(["A", "B", "C"])
    root = build_hide_and_seek_sub(_ctx())
    assert isinstance(root, py_trees.composites.Sequence)
    assert root.name == "BT_patrol_sub"
    assert len(root.children) == 3


def test_waypoint_order_preserved():
    _set_search_waypoints(["foo", "bar"])
    root = build_hide_and_seek_sub(_ctx())
    # FailureIsSuccess 로 감싸진 visit Sequence — 이름이 visit_<name>
    visit_names = [safe.children[0].name for safe in root.children]
    assert visit_names == ["visit_foo", "visit_bar"]


def test_returns_failure_when_waypoints_empty():
    _set_search_waypoints([])
    root = build_hide_and_seek_sub(_ctx())
    assert isinstance(root, py_trees.behaviours.Failure)
    assert root.name == "BT_hide_and_seek_sub_no_waypoints"


def test_returns_failure_when_waypoints_unset():
    # init_blackboard 안 호출 — 키 자체가 없는 상황 (clear 됨)
    root = build_hide_and_seek_sub(_ctx())
    assert isinstance(root, py_trees.behaviours.Failure)


def test_failure_leaf_ticks_to_failure_status():
    """반환된 Failure leaf 가 실제로 FAILURE status 로 tick 되는지."""
    _set_search_waypoints([])
    root = build_hide_and_seek_sub(_ctx())
    root.tick_once()
    assert root.status == py_trees.common.Status.FAILURE
