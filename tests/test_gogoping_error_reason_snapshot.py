"""snapshot() 결과에 error_reason 포함 — robot-web ERROR 오버레이가 사유 표시에 사용.

fault trigger 가 blackboard.error_reason 을 set (e.g. "out_of_map", "lidar_timeout").
snapshot 이 그대로 통과 — 미설정/예외 시 "".
"""
from __future__ import annotations

import sys
from pathlib import Path

import py_trees
from py_trees.common import Access

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.blackboard import Keys, init_blackboard  # noqa: E402
from gogoping_modes.bt.tree_inspector import snapshot  # noqa: E402


def setup_function(_):
    py_trees.blackboard.Blackboard.clear()
    import gogoping_modes.bt.tree_inspector as ti
    ti._bb_reader = None
    init_blackboard()


def _set(key, value):
    bb = py_trees.blackboard.Client(name="setter")
    bb.register_key(key=key, access=Access.WRITE)
    bb.set(key, value)


def _stub_root():
    root = py_trees.composites.Sequence(name="root", memory=True)
    root.add_child(py_trees.behaviours.Success(name="leaf"))
    root.tick_once()
    return root


def test_snapshot_includes_error_reason_default_empty():
    """init_blackboard 직후 (ERROR_REASON default = "") → snapshot 도 ""."""
    snap = snapshot(fsm_state="IDLE", root_tree=_stub_root())
    assert snap["error_reason"] == ""


def test_snapshot_reflects_error_reason_value():
    """ERROR_REASON 을 "out_of_map" 으로 W → snapshot 도 "out_of_map"."""
    _set(Keys.ERROR_REASON, "out_of_map")
    snap = snapshot(fsm_state="ERROR", root_tree=_stub_root())
    assert snap["error_reason"] == "out_of_map"


def test_snapshot_error_reason_passes_through_regardless_of_state():
    """fsm_state 가 ERROR 가 아니어도 blackboard 값이 그대로 통과되는지 검증.

    snapshot 은 state 필터를 하지 않는다 (소비자가 ERROR 일 때만 사용). 이 속성을
    명시적으로 고정 — 누군가 state 게이팅을 추가하면 이 테스트가 깨진다.
    """
    _set(Keys.ERROR_REASON, "lidar_timeout")
    snap = snapshot(fsm_state="IDLE", root_tree=_stub_root())
    assert snap["error_reason"] == "lidar_timeout"
