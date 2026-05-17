"""IDLE state MainTree — 명령 대기.

Day 1 walking skeleton: CommandListener 만 (배터리/HW monitor 는 Day 2).

진짜 Day 2 모양 (``docs/state-bt.md``):
    Parallel
      ├─ BatteryLowMonitor    (Day 2)
      ├─ HardwareHealthMonitor (Day 2)
      └─ CommandListener      (Day 1 ✅)
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.common.command_listener import CommandListener


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_idle_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            CommandListener("CommandListener", ctx),
            # TODO Day 2: BatteryLowMonitor, HardwareHealthMonitor
        ],
    )
