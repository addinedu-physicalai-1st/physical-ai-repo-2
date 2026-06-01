"""Countdown behaviour — N 초 경과 후 SUCCESS + debug skip 키 지원."""
from __future__ import annotations

from unittest.mock import patch

import py_trees
from py_trees.common import Access

from gogoping_modes.bt.behaviors.hide_and_seek.countdown import Countdown
from gogoping_modes.bt.blackboard import Keys, init_blackboard


def _set_skip(key: str, value: bool) -> None:
    bb = py_trees.blackboard.Client(name="test_setter")
    bb.register_key(key=key, access=Access.WRITE)
    bb.set(key, value)


def _read(key: str) -> object:
    bb = py_trees.blackboard.Client(name="test_reader")
    bb.register_key(key=key, access=Access.READ)
    return bb.get(key)


def test_countdown_running_before_elapsed():
    bh = Countdown(name="cd", seconds=3.0)
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=100.0):
        bh.setup()
        bh.initialise()
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=101.0):
        status = bh.update()
    assert status == py_trees.common.Status.RUNNING


def test_countdown_success_after_elapsed():
    bh = Countdown(name="cd", seconds=3.0)
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=100.0):
        bh.setup()
        bh.initialise()
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=103.5):
        status = bh.update()
    assert status == py_trees.common.Status.SUCCESS


def test_countdown_resets_on_reinitialise():
    """interrupt 후 재진입 시 다시 N 초 카운트."""
    bh = Countdown(name="cd", seconds=2.0)
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=100.0):
        bh.setup()
        bh.initialise()
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=101.5):
        assert bh.update() == py_trees.common.Status.RUNNING
    # 재진입 — terminate 후 initialise (py_trees 가 RUNNING 끝나면 호출)
    bh.terminate(py_trees.common.Status.INVALID)
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=200.0):
        bh.initialise()
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=201.5):
        assert bh.update() == py_trees.common.Status.RUNNING  # 새로 시작
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=202.5):
        assert bh.update() == py_trees.common.Status.SUCCESS


def test_countdown_skip_via_blackboard():
    """check_skip_key 지정 시 blackboard True → 즉시 SUCCESS + flag reset."""
    py_trees.blackboard.Blackboard.clear()
    init_blackboard()
    bh = Countdown(
        name="cd", seconds=30.0, check_skip_key=Keys.HIDESEEK_SKIP_COUNTDOWN,
    )
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=100.0):
        bh.setup()
        bh.initialise()
    # 초기엔 flag False — RUNNING
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=101.0):
        assert bh.update() == py_trees.common.Status.RUNNING

    # flag True 셋 → 즉시 SUCCESS
    _set_skip(Keys.HIDESEEK_SKIP_COUNTDOWN, True)
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=102.0):
        assert bh.update() == py_trees.common.Status.SUCCESS
    # flag 자동 reset (다음 진입 시 정상 동작)
    assert _read(Keys.HIDESEEK_SKIP_COUNTDOWN) is False


def test_countdown_skip_key_none_disabled():
    """check_skip_key=None 인 기본 Countdown 은 blackboard 영향 없음 (회귀)."""
    py_trees.blackboard.Blackboard.clear()
    init_blackboard()
    bh = Countdown(name="cd", seconds=10.0)  # check_skip_key default None
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=100.0):
        bh.setup()
        bh.initialise()
    # flag 셋해도 RUNNING (Countdown 이 키 안 봄)
    _set_skip(Keys.HIDESEEK_SKIP_COUNTDOWN, True)
    with patch("gogoping_modes.bt.behaviors.hide_and_seek.countdown.time.monotonic", return_value=101.0):
        assert bh.update() == py_trees.common.Status.RUNNING
