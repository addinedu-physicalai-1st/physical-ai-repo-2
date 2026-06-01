"""AwaitRecruitComplete — blackboard.hideseek_registered_ids 비어있지 않으면 SUCCESS."""
from __future__ import annotations

import py_trees
from py_trees.common import Access

from gogoping_modes.bt.behaviors.hide_and_seek.await_recruit_complete import (
    AwaitRecruitComplete,
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
    bh = AwaitRecruitComplete(name="await")
    bh.setup()
    bh.initialise()
    assert bh.update() == py_trees.common.Status.RUNNING


def test_success_when_registered_nonempty():
    _set(Keys.HIDESEEK_REGISTERED_IDS, [1, 3, 7])
    bh = AwaitRecruitComplete(name="await")
    bh.setup()
    bh.initialise()
    assert bh.update() == py_trees.common.Status.SUCCESS
