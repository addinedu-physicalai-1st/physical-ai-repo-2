"""BT_hide_and_seek_sub 확장 — Sequence 6 step 빌더 검증.

기존 patrol-only 빌더가 6 step (move → recruit → countdown → patrol → return → end)
Sequence 로 확장되었는지 확인. 명세: docs/bt/trees/BT_hide_and_seek_sub.md.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import py_trees
from py_trees.common import Access

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.blackboard import Keys, init_blackboard  # noqa: E402
from gogoping_modes.bt.trees.sub_trees.BT_hide_and_seek_sub import build_hide_and_seek_sub  # noqa: E402


def _ctx_stub():
    ctx = MagicMock()
    ctx.camera_pan = MagicMock()
    ctx.node = MagicMock()
    return ctx


def _set(key, value):
    bb = py_trees.blackboard.Client(name="test_setter")
    bb.register_key(key=key, access=Access.WRITE)
    bb.set(key, value)


def setup_function(_):
    py_trees.blackboard.Blackboard.clear()
    init_blackboard()


def test_builder_returns_sequence_with_6_steps():
    """play_area 와 search_waypoints 둘 다 있을 때 6 step Sequence 반환."""
    _set(Keys.HIDESEEK_PLAY_AREA_KEY, "play_area")
    _set(Keys.SEARCH_WAYPOINTS, ["patrol_slide", "patrol_sandbox"])
    root = build_hide_and_seek_sub(_ctx_stub())
    assert isinstance(root, py_trees.composites.Sequence)
    # 모든 leaf/composite 이름 평탄화 후 phase marker 6개 다 있는지 확인.
    names = [n.name for n in root.iterate()]
    phase_set_names = [n for n in names if n.startswith("set_phase_")]
    assert "set_phase_move_to_play" in phase_set_names
    assert "set_phase_recruit" in phase_set_names
    assert "set_phase_countdown" in phase_set_names
    assert "set_phase_patrol" in phase_set_names
    assert "set_phase_return" in phase_set_names
    assert "set_phase_end" in phase_set_names


def test_builder_end_step_has_running_idle():
    """마지막 step 은 SetHideseekPhase("end") + Running() — root SUCCESS 막아
    end phase UI 가 사용자 명시 cancel 까지 떠있도록 한다.
    """
    _set(Keys.HIDESEEK_PLAY_AREA_KEY, "play_area")
    _set(Keys.SEARCH_WAYPOINTS, ["patrol_a"])
    root = build_hide_and_seek_sub(_ctx_stub())
    # 마지막 child = step_end (Sequence). children 인덱싱 가능.
    last = root.children[-1]
    assert last.name == "step_end"
    # step_end 의 마지막 자식이 Running 인스턴스.
    last_leaf = last.children[-1]
    assert isinstance(last_leaf, py_trees.behaviours.Running)


def test_builder_rejects_missing_play_area():
    """play_area 미설정이면 Failure leaf 반환."""
    _set(Keys.HIDESEEK_PLAY_AREA_KEY, "")
    _set(Keys.SEARCH_WAYPOINTS, ["patrol_a"])
    root = build_hide_and_seek_sub(_ctx_stub())
    assert isinstance(root, py_trees.behaviours.Failure)


def test_builder_rejects_missing_waypoints():
    """search_waypoints 빈 리스트면 Failure leaf."""
    _set(Keys.HIDESEEK_PLAY_AREA_KEY, "play_area")
    _set(Keys.SEARCH_WAYPOINTS, [])
    root = build_hide_and_seek_sub(_ctx_stub())
    assert isinstance(root, py_trees.behaviours.Failure)


def test_builder_patrol_only_returns_patrol_sub_only():
    """HIDESEEK_PATROL_ONLY=True 면 SetHideseekPhase("patrol") + patrol_sub 만 (no 6-step).

    admin UI [순찰] 모드 — 모집/카운트다운/이동/복귀 다 skip.
    """
    _set(Keys.HIDESEEK_PLAY_AREA_KEY, "play_area")
    _set(Keys.SEARCH_WAYPOINTS, ["a", "b", "c"])
    _set(Keys.HIDESEEK_PATROL_ONLY, True)
    root = build_hide_and_seek_sub(_ctx_stub())
    # patrol_only Sequence — 자식 2개 (SetHideseekPhase, BT_patrol_sub)
    assert isinstance(root, py_trees.composites.Sequence)
    assert root.name == "BT_hide_and_seek_sub_patrol_only"
    names = [c.name for c in root.children]
    assert names[0] == "set_phase_patrol_only"
    assert names[1] == "BT_patrol_sub"
    # 6-step 식별 마커 부재 확인
    assert "set_phase_recruit" not in [n.name for n in root.iterate()]
    assert "set_phase_countdown" not in [n.name for n in root.iterate()]


def test_builder_patrol_only_does_not_need_play_area():
    """patrol_only=True 면 play_area 없어도 OK — 모집/이동 step 자체 없으니까."""
    # play_area 미설정 (clear 후 default 안 됨)
    _set(Keys.SEARCH_WAYPOINTS, ["a"])
    _set(Keys.HIDESEEK_PATROL_ONLY, True)
    root = build_hide_and_seek_sub(_ctx_stub())
    assert isinstance(root, py_trees.composites.Sequence)
    assert root.name == "BT_hide_and_seek_sub_patrol_only"
