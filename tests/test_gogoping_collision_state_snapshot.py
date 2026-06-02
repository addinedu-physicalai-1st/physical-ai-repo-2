"""snapshot() 결과에 collision_state 포함 — admin UI 가 "ok" / "stop" 실시간 표시에 사용.

collision_subscriber 가 nav2 collision_monitor state 토픽을 받아 blackboard.COLLISION_STATE
를 "ok" / "stop" 으로 W. snapshot 이 그대로 통과 — 미설정/예외 시 "".

CollisionMonitor leaf 는 항상 RUNNING 만 반환해 트리뷰 status 로는 stop 여부를 알 수 없으므로,
실제 collision 값은 이 필드로만 운영자에게 노출된다.
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


def test_snapshot_includes_collision_state_default_ok():
    """init_blackboard 직후 (COLLISION_STATE default = "ok") → snapshot 도 "ok"."""
    snap = snapshot(fsm_state="IDLE", root_tree=_stub_root())
    assert snap["collision_state"] == "ok"


def test_snapshot_reflects_collision_state_stop():
    """COLLISION_STATE 를 "stop" 으로 W → snapshot 도 "stop"."""
    _set(Keys.COLLISION_STATE, "stop")
    snap = snapshot(fsm_state="GOTO", root_tree=_stub_root())
    assert snap["collision_state"] == "stop"


def test_snapshot_collision_state_passes_through_regardless_of_state():
    """fsm_state 와 무관하게 blackboard 값이 그대로 통과되는지 고정.

    snapshot 은 state 필터를 하지 않는다 — 누군가 state 게이팅을 추가하면 이 테스트가 깨진다.
    """
    _set(Keys.COLLISION_STATE, "stop")
    snap = snapshot(fsm_state="FOLLOW", root_tree=_stub_root())
    assert snap["collision_state"] == "stop"
