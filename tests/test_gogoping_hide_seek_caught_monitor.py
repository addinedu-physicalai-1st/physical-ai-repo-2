"""HideSeekCaughtMonitor — registered ⊆ caught 이면 SUCCESS."""
from __future__ import annotations

import py_trees
from py_trees.common import Access

from gogoping_modes.bt.behaviors.perception.hide_seek_caught_monitor import (
    HideSeekCaughtMonitor,
)
from gogoping_modes.bt.blackboard import Keys, init_blackboard


def _set(key, value):
    bb = py_trees.blackboard.Client(name="test_setter")
    bb.register_key(key=key, access=Access.WRITE)
    bb.set(key, value)


def setup_function(_):
    py_trees.blackboard.Blackboard.clear()
    init_blackboard()


def test_running_when_registered_empty():
    """registered_ids 비어있으면 (모집 진행 전) RUNNING — 의도적으로 SUCCESS 안 함."""
    bh = HideSeekCaughtMonitor(name="caught_mon")
    bh.setup()
    bh.initialise()
    assert bh.update() == py_trees.common.Status.RUNNING


def test_running_when_partial_caught():
    _set(Keys.HIDESEEK_REGISTERED_IDS, [1, 2, 3])
    _set(Keys.HIDESEEK_CAUGHT_IDS, [1])
    bh = HideSeekCaughtMonitor(name="caught_mon")
    bh.setup()
    bh.initialise()
    assert bh.update() == py_trees.common.Status.RUNNING


def test_success_when_all_caught():
    _set(Keys.HIDESEEK_REGISTERED_IDS, [1, 2, 3])
    _set(Keys.HIDESEEK_CAUGHT_IDS, [3, 2, 1])  # order 무관
    bh = HideSeekCaughtMonitor(name="caught_mon")
    bh.setup()
    bh.initialise()
    assert bh.update() == py_trees.common.Status.SUCCESS


def test_success_when_caught_superset():
    """caught 에 registered 외 child_id 가 섞여도 (이론상 불가) registered 가 ⊆ 이면 SUCCESS."""
    _set(Keys.HIDESEEK_REGISTERED_IDS, [1, 2])
    _set(Keys.HIDESEEK_CAUGHT_IDS, [1, 2, 99])
    bh = HideSeekCaughtMonitor(name="caught_mon")
    bh.setup()
    bh.initialise()
    assert bh.update() == py_trees.common.Status.SUCCESS
