"""BatteryLowMonitor / BatteryFullMonitor 단위 테스트.

ROS 의존성 없음 — py_trees 만 사용. context.fsm 은 MockFSM 으로 대체.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# gogoping_modes 패키지 path 등록
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

import py_trees  # noqa: E402
from py_trees.common import Access  # noqa: E402

# blackboard / behavior imports
from gogoping_modes.bt.blackboard import Keys, init_blackboard  # noqa: E402
from gogoping_modes.bt.behaviors.common.battery_full_monitor import BatteryFullMonitor  # noqa: E402
from gogoping_modes.bt.behaviors.common.battery_low_monitor import BatteryLowMonitor  # noqa: E402


class _MockFSM:
    """fsm.trigger() 호출만 기록."""
    def __init__(self) -> None:
        self.calls: list[str] = []

    def trigger(self, name: str, **_kwargs) -> None:
        self.calls.append(name)


class _Ctx:
    def __init__(self) -> None:
        self.fsm = _MockFSM()


@pytest.fixture
def bb_writer():
    """전역 blackboard 초기화 + 테스트가 BATTERY_LEVEL 쓸 client 반환."""
    init_blackboard()
    client = py_trees.blackboard.Client(name="test_writer")
    client.register_key(key=Keys.BATTERY_LEVEL, access=Access.WRITE)
    return client


# ----------------------------------------------------------- BatteryLowMonitor

def test_low_monitor_no_fire_above_threshold(bb_writer):
    ctx = _Ctx()
    mon = BatteryLowMonitor("low", ctx); mon.setup(); mon.initialise()
    bb_writer.set(Keys.BATTERY_LEVEL, 100.0)
    mon.update()
    assert ctx.fsm.calls == []


def test_low_monitor_no_fire_at_hysteresis_band(bb_writer):
    """LOW_EXIT (25%) 보다 위면 fire 안 함 (진입 임계 20% 안 들어감)."""
    ctx = _Ctx()
    mon = BatteryLowMonitor("low", ctx); mon.setup(); mon.initialise()
    bb_writer.set(Keys.BATTERY_LEVEL, 25.0)
    mon.update()
    assert ctx.fsm.calls == []


def test_low_monitor_fires_at_enter(bb_writer):
    ctx = _Ctx()
    mon = BatteryLowMonitor("low", ctx); mon.setup(); mon.initialise()
    bb_writer.set(Keys.BATTERY_LEVEL, 20.0)
    mon.update()
    assert ctx.fsm.calls == ["battery_low"]


def test_low_monitor_no_double_fire(bb_writer):
    ctx = _Ctx()
    mon = BatteryLowMonitor("low", ctx); mon.setup(); mon.initialise()
    bb_writer.set(Keys.BATTERY_LEVEL, 20.0); mon.update()
    bb_writer.set(Keys.BATTERY_LEVEL, 10.0); mon.update()
    assert ctx.fsm.calls == ["battery_low"]


def test_low_monitor_hysteresis_refire(bb_writer):
    """20% fire → 26% reset → 20% re-fire."""
    ctx = _Ctx()
    mon = BatteryLowMonitor("low", ctx); mon.setup(); mon.initialise()
    bb_writer.set(Keys.BATTERY_LEVEL, 20.0); mon.update()
    bb_writer.set(Keys.BATTERY_LEVEL, 26.0); mon.update()  # reset
    bb_writer.set(Keys.BATTERY_LEVEL, 20.0); mon.update()  # re-fire
    assert ctx.fsm.calls == ["battery_low", "battery_low"]


def test_low_monitor_initialise_rearm(bb_writer):
    """initialise() 호출 시 _fired 리셋 — 트리 swap 후 재진입 보장."""
    ctx = _Ctx()
    mon = BatteryLowMonitor("low", ctx); mon.setup(); mon.initialise()
    bb_writer.set(Keys.BATTERY_LEVEL, 20.0); mon.update()  # fire
    mon.initialise()                                       # re-enter tree
    bb_writer.set(Keys.BATTERY_LEVEL, 20.0); mon.update()  # re-fire
    assert ctx.fsm.calls == ["battery_low", "battery_low"]


# ----------------------------------------------------------- BatteryFullMonitor

def test_full_monitor_no_fire_below_threshold(bb_writer):
    ctx = _Ctx()
    mon = BatteryFullMonitor("full", ctx); mon.setup(); mon.initialise()
    bb_writer.set(Keys.BATTERY_LEVEL, 60.0)
    mon.update()
    assert ctx.fsm.calls == []


def test_full_monitor_fires_at_enter(bb_writer):
    ctx = _Ctx()
    mon = BatteryFullMonitor("full", ctx); mon.setup(); mon.initialise()
    bb_writer.set(Keys.BATTERY_LEVEL, 70.0)
    mon.update()
    assert ctx.fsm.calls == ["battery_full"]


def test_full_monitor_no_double_fire(bb_writer):
    ctx = _Ctx()
    mon = BatteryFullMonitor("full", ctx); mon.setup(); mon.initialise()
    bb_writer.set(Keys.BATTERY_LEVEL, 70.0); mon.update()
    bb_writer.set(Keys.BATTERY_LEVEL, 90.0); mon.update()
    assert ctx.fsm.calls == ["battery_full"]
