"""BrakeAndWait 단위 테스트.

- initialise() 시 cmd_vel=0 즉시 publish (1회)
- update() 매 tick cmd_vel=0 계속 publish
- duration_sec 경과 시 SUCCESS
- pub None 일 때 예외 없이 진행
- publish exception 잡고 진행 (logger.warning)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import py_trees
from py_trees.common import Status

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from gogoping_modes.bt.behaviors.navigation.brake_and_wait import BrakeAndWait  # noqa: E402


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start

    def now(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _ctx_with_pub():
    ctx = MagicMock()
    ctx.cmd_vel_pub = MagicMock()
    return ctx


def setup_function():
    py_trees.blackboard.Blackboard.clear()


def test_initialise_publishes_zero_once():
    ctx = _ctx_with_pub()
    clk = FakeClock()
    leaf = BrakeAndWait("brake", ctx, duration_sec=0.5, now_fn=clk.now)
    leaf.initialise()
    assert ctx.cmd_vel_pub.publish.call_count == 1
    msg = ctx.cmd_vel_pub.publish.call_args.args[0]
    assert msg.linear.x == 0.0 and msg.angular.z == 0.0


def test_update_keeps_publishing_zero_each_tick():
    ctx = _ctx_with_pub()
    clk = FakeClock()
    leaf = BrakeAndWait("brake", ctx, duration_sec=0.5, now_fn=clk.now)
    leaf.initialise()  # publish 1
    leaf.update()      # publish 2
    leaf.update()      # publish 3
    assert ctx.cmd_vel_pub.publish.call_count == 3


def test_returns_running_before_duration():
    ctx = _ctx_with_pub()
    clk = FakeClock()
    leaf = BrakeAndWait("brake", ctx, duration_sec=0.5, now_fn=clk.now)
    leaf.initialise()
    clk.advance(0.2)
    assert leaf.update() == Status.RUNNING
    clk.advance(0.2)
    assert leaf.update() == Status.RUNNING


def test_returns_success_after_duration():
    ctx = _ctx_with_pub()
    clk = FakeClock()
    leaf = BrakeAndWait("brake", ctx, duration_sec=0.5, now_fn=clk.now)
    leaf.initialise()
    clk.advance(0.5)
    assert leaf.update() == Status.SUCCESS


def test_returns_success_just_past_duration():
    ctx = _ctx_with_pub()
    clk = FakeClock()
    leaf = BrakeAndWait("brake", ctx, duration_sec=0.5, now_fn=clk.now)
    leaf.initialise()
    clk.advance(0.51)
    assert leaf.update() == Status.SUCCESS


def test_no_cmd_vel_pub_attribute_no_crash():
    ctx = MagicMock(spec=[])  # 빈 spec — cmd_vel_pub 없음
    clk = FakeClock()
    leaf = BrakeAndWait("brake", ctx, duration_sec=0.5, now_fn=clk.now)
    leaf.initialise()
    clk.advance(0.5)
    assert leaf.update() == Status.SUCCESS


def test_publish_exception_swallowed():
    ctx = _ctx_with_pub()
    ctx.cmd_vel_pub.publish.side_effect = RuntimeError("network down")
    clk = FakeClock()
    leaf = BrakeAndWait("brake", ctx, duration_sec=0.5, now_fn=clk.now)
    leaf.initialise()
    clk.advance(0.5)
    assert leaf.update() == Status.SUCCESS


def test_terminate_is_noop():
    ctx = _ctx_with_pub()
    clk = FakeClock()
    leaf = BrakeAndWait("brake", ctx, duration_sec=0.5, now_fn=clk.now)
    leaf.initialise()
    leaf.terminate(Status.INVALID)
    # publish 추가 호출 없음 — initialise 1회만
    assert ctx.cmd_vel_pub.publish.call_count == 1
