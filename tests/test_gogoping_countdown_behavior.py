"""Countdown behaviour — N 초 경과 후 SUCCESS."""
from __future__ import annotations

from unittest.mock import patch

import py_trees

from gogoping_modes.bt.behaviors.common.countdown import Countdown


def test_countdown_running_before_elapsed():
    bh = Countdown(name="cd", seconds=3.0)
    with patch("gogoping_modes.bt.behaviors.common.countdown.time.monotonic", return_value=100.0):
        bh.setup()
        bh.initialise()
    with patch("gogoping_modes.bt.behaviors.common.countdown.time.monotonic", return_value=101.0):
        status = bh.update()
    assert status == py_trees.common.Status.RUNNING


def test_countdown_success_after_elapsed():
    bh = Countdown(name="cd", seconds=3.0)
    with patch("gogoping_modes.bt.behaviors.common.countdown.time.monotonic", return_value=100.0):
        bh.setup()
        bh.initialise()
    with patch("gogoping_modes.bt.behaviors.common.countdown.time.monotonic", return_value=103.5):
        status = bh.update()
    assert status == py_trees.common.Status.SUCCESS


def test_countdown_resets_on_reinitialise():
    """interrupt 후 재진입 시 다시 N 초 카운트."""
    bh = Countdown(name="cd", seconds=2.0)
    with patch("gogoping_modes.bt.behaviors.common.countdown.time.monotonic", return_value=100.0):
        bh.setup()
        bh.initialise()
    with patch("gogoping_modes.bt.behaviors.common.countdown.time.monotonic", return_value=101.5):
        assert bh.update() == py_trees.common.Status.RUNNING
    # 재진입 — terminate 후 initialise (py_trees 가 RUNNING 끝나면 호출)
    bh.terminate(py_trees.common.Status.INVALID)
    with patch("gogoping_modes.bt.behaviors.common.countdown.time.monotonic", return_value=200.0):
        bh.initialise()
    with patch("gogoping_modes.bt.behaviors.common.countdown.time.monotonic", return_value=201.5):
        assert bh.update() == py_trees.common.Status.RUNNING  # 새로 시작
    with patch("gogoping_modes.bt.behaviors.common.countdown.time.monotonic", return_value=202.5):
        assert bh.update() == py_trees.common.Status.SUCCESS
