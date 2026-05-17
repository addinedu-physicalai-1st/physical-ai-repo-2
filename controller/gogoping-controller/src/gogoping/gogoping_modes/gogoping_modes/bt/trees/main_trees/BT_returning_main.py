"""RETURNING state MainTree — 도크로 자율 복귀 중.

현재 stub: CommandListener + BatteryLowMonitor (HW monitor / ReturnSubTree 는 추후).

BatteryLowMonitor 는 escalation 용 — RETURNING 도중에도 배터리 더 떨어지면
``battery_low`` trigger 발화 → LOW_BATTERY_RETURN lockdown 으로 전환.
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.common.battery_low_monitor import BatteryLowMonitor
from ...behaviors.common.command_listener import CommandListener
from ...behaviors.common.map_boundary_monitor import MapBoundaryMonitor


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_returning_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            BatteryLowMonitor("BatteryLowMonitor", ctx),
            MapBoundaryMonitor("MapBoundaryMonitor", ctx),
            CommandListener("CommandListener", ctx),
            # TODO 추후: HardwareHealthMonitor, CollisionEventHandler, ReturnSubTree
        ],
    )
