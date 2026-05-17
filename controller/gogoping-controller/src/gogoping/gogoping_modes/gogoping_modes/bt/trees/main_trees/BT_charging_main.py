"""CHARGING state MainTree — 도크에서 충전 중.

Day 1 walking skeleton: CommandListener + BatteryFullMonitor.
Day 2 에 추가될 monitor: HardwareHealthMonitor, DockingContactCheck.

BatteryFullMonitor 가 핵심 — 부팅 직후 CHARGING → IDLE 전이를 자동화. Day 1 에선
BatterySubscriber stub 이라 BATTERY_LEVEL 이 init 값 (100.0) 이라 첫 tick 에 즉시 fire,
사용자가 의도한 "부팅=CHARGING, 배터리 정상이면 IDLE" 시퀀스 자연 재현.
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.common.battery_full_monitor import BatteryFullMonitor
from ...behaviors.common.command_listener import CommandListener


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_charging_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            BatteryFullMonitor("BatteryFullMonitor", ctx),
            CommandListener("CommandListener", ctx),
            # TODO Day 2: HardwareHealthMonitor, DockingContactCheck
        ],
    )
