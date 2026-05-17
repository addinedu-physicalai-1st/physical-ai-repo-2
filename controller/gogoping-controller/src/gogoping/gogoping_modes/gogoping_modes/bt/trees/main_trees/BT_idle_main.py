"""IDLE state MainTree — 명령 대기.

현재 stub: CommandListener 만 (배터리/HW monitor 는 ).

진짜 추후 모양 (``docs/state-bt.md``):
    Parallel
      ├─ BatteryLowMonitor   
      ├─ HardwareHealthMonitor
      └─ CommandListener      (추후 ✅)
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
            # TODO 추후: BatteryLowMonitor, HardwareHealthMonitor
        ],
    )
