"""snapshot() 결과에 hideseek_phase 포함 — UI WS 가 라우팅에 사용.

UI (robot-web `useGogopingStateWs`) 가 `/ws/robot-state` 로 받아서 화면 라우팅에
쓰는 필드. blackboard.HIDESEEK_PHASE 를 그대로 통과 — 미설정/예외 시 "".
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
    # tree_inspector 가 모듈 캐시한 reader 도 리셋 — register_key 가 새 blackboard 에서
    # 다시 발생하도록.
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


def test_snapshot_includes_hideseek_phase_default_empty():
    """init_blackboard 직후 (HIDESEEK_PHASE 의 default = "") → snapshot 도 ""."""
    snap = snapshot(fsm_state="IDLE", root_tree=_stub_root())
    assert snap["hideseek_phase"] == ""


def test_snapshot_reflects_phase_value():
    """HIDESEEK_PHASE 를 "patrol" 로 W → snapshot 도 "patrol"."""
    _set(Keys.HIDESEEK_PHASE, "patrol")
    snap = snapshot(fsm_state="HIDEANDSEEK", root_tree=_stub_root())
    assert snap["hideseek_phase"] == "patrol"
