"""SetPatrolIndex 단위 테스트.

- update() 1 tick: BB.patrol_current_index = index 쓰고 SUCCESS
- index 음수/0/양수 모두 OK
"""
from __future__ import annotations

import sys
from pathlib import Path

import py_trees
from py_trees.common import Access, Status

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.behaviors.patrol.set_patrol_index import SetPatrolIndex  # noqa: E402
from gogoping_modes.bt.blackboard import Keys  # noqa: E402


def setup_function():
    py_trees.blackboard.Blackboard.clear()


def _read():
    bb = py_trees.blackboard.Client(name="reader")
    bb.register_key(key=Keys.PATROL_CURRENT_INDEX, access=Access.READ)
    return bb.get(Keys.PATROL_CURRENT_INDEX)


def test_writes_index_zero():
    leaf = SetPatrolIndex("set", 0)
    assert leaf.update() == Status.SUCCESS
    assert _read() == 0


def test_writes_positive_index():
    leaf = SetPatrolIndex("set", 5)
    leaf.update()
    assert _read() == 5


def test_writes_done_marker_n():
    """vertex N 개 다 끝났을 때 patrol_sub 가 SetPatrolIndex(N) 으로 표시."""
    leaf = SetPatrolIndex("set", 23)
    leaf.update()
    assert _read() == 23


def test_writes_negative_idle_marker():
    leaf = SetPatrolIndex("set", -1)
    leaf.update()
    assert _read() == -1


def test_repeated_writes_overwrite():
    SetPatrolIndex("a", 0).update()
    SetPatrolIndex("b", 1).update()
    SetPatrolIndex("c", 2).update()
    assert _read() == 2
