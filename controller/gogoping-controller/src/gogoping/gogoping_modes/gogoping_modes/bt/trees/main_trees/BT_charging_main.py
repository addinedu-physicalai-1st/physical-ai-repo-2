"""CHARGING state MainTree — 도크에서 충전 중.

Day 1 walking skeleton: CommandListener 만 (battery_full / docking_contact monitor 는 Day 2).

진짜 Day 2 모양:
    Parallel
      ├─ BatteryFullMonitor   (Day 2 — 80% 도달 시 battery_full trigger)
      ├─ HardwareHealthMonitor (Day 2)
      └─ DockingContactCheck  (Day 2 — 접점 끊기면 fault)
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.common.command_listener import CommandListener


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_charging_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            CommandListener("CommandListener", ctx),
            # TODO Day 2: BatteryFullMonitor, HardwareHealthMonitor, DockingContactCheck
        ],
    )
