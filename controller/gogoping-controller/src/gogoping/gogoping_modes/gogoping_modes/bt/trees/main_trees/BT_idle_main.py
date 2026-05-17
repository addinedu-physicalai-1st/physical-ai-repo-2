"""IDLE state MainTree — 명령 대기.

현재 stub: CommandListener + BatteryLowMonitor (HW monitor 는 추후).

진짜 추후 모양 (``docs/state-bt.md``):
    Parallel
      ├─ BatteryLowMonitor      (✅)
      ├─ HardwareHealthMonitor  (추후)
      └─ CommandListener        (✅)
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.common.battery_low_monitor import BatteryLowMonitor
from ...behaviors.common.command_listener import CommandListener


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_idle_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            BatteryLowMonitor("BatteryLowMonitor", ctx),
            CommandListener("CommandListener", ctx),
            # TODO 추후: HardwareHealthMonitor
        ],
    )
