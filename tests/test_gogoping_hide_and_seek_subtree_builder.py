"""BT_hide_and_seek_sub 빌더 단위 테스트 (6-step Sequence).

빌더는 blackboard 의 ``hideseek_play_area_key`` 와 ``search_waypoints`` 둘 다 읽어:
- 둘 다 채워졌으면 → ``Sequence("BT_hide_and_seek_sub", memory=True)`` 6 step 반환
- play_area 비어있으면 → ``Failure("BT_hide_and_seek_sub_no_play_area")``
- search_waypoints 비어있으면 → ``Failure("BT_hide_and_seek_sub_no_waypoints")``

정상 경로에선 reconciler 가 빈 값을 미리 차단하지만, ForceState 디버그 우회
시나리오 방어를 위해 빌더 자체도 깨지지 않아야 한다.

6-step 의 더 상세한 구조 검증은 ``test_gogoping_hideseek_subtree_sequence.py``.
본 파일은 기존 patrol-only 시절의 핵심 invariant (waypoint 순서 보존, Failure 분기) 를
신 6-step 빌더에서도 유지하는지 확인.
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


def _set(key, value):
    bb = py_trees.blackboard.Client(name="test_setup")
    bb.register_key(key=key, access=Access.WRITE)
    bb.set(key, value)


def _set_search_waypoints(wps):
    _set(Keys.SEARCH_WAYPOINTS, wps)


def _find_subtree(root, name):
    """Recursively find a descendant by name (used to dig into BT_patrol_sub inside step_patrol)."""
    for n in root.iterate():
        if n.name == name:
            return n
    return None


def test_returns_sequence_when_play_area_and_waypoints_present():
    """play_area + waypoints 둘 다 있으면 6-step Sequence("BT_hide_and_seek_sub")."""
    _set(Keys.HIDESEEK_PLAY_AREA_KEY, "운동장2")
    _set_search_waypoints(["A", "B", "C"])
    root = build_hide_and_seek_sub(_ctx())
    assert isinstance(root, py_trees.composites.Sequence)
    assert root.name == "BT_hide_and_seek_sub"
    # 6 step 자식 — step_move_to_play / step_recruit / step_countdown / step_patrol / step_return / step_end
    assert len(root.children) == 6


def test_waypoint_order_preserved_inside_patrol_step():
    """search_waypoints 순서가 step_patrol 안 BT_patrol_sub 의 visit Sequence 들에서 보존되는지."""
    _set(Keys.HIDESEEK_PLAY_AREA_KEY, "운동장2")
    _set_search_waypoints(["foo", "bar"])
    root = build_hide_and_seek_sub(_ctx())
    # BT_patrol_sub 는 step_patrol → patrol_with_caught_monitor → BT_patrol_sub.
    patrol_sub = _find_subtree(root, "BT_patrol_sub")
    assert patrol_sub is not None
    # FailureIsSuccess 로 감싸진 visit Sequence — 이름이 visit_<name>. 마지막은 done marker 제외.
    visit_names = [safe.children[0].name for safe in patrol_sub.children[:-1]]
    assert visit_names == ["visit_foo", "visit_bar"]


def test_returns_failure_when_waypoints_empty():
    """play_area 는 있지만 search_waypoints 가 빈 리스트면 Failure(no_waypoints)."""
    _set(Keys.HIDESEEK_PLAY_AREA_KEY, "운동장2")
    _set_search_waypoints([])
    root = build_hide_and_seek_sub(_ctx())
    assert isinstance(root, py_trees.behaviours.Failure)
    assert root.name == "BT_hide_and_seek_sub_no_waypoints"


def test_returns_failure_when_waypoints_unset():
    """init_blackboard 미호출 — play_area / waypoints 둘 다 미정 → Failure (어떤 종류든)."""
    # 키 자체가 없는 상황 (clear 됨). play_area check 가 먼저라 _no_play_area.
    root = build_hide_and_seek_sub(_ctx())
    assert isinstance(root, py_trees.behaviours.Failure)


def test_failure_leaf_ticks_to_failure_status():
    """반환된 Failure leaf 가 실제로 FAILURE status 로 tick 되는지."""
    _set(Keys.HIDESEEK_PLAY_AREA_KEY, "운동장2")
    _set_search_waypoints([])
    root = build_hide_and_seek_sub(_ctx())
    root.tick_once()
    assert root.status == py_trees.common.Status.FAILURE
