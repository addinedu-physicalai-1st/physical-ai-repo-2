"""RETURNING state MainTree — 도크로 자율 복귀 중.

Day 1 walking skeleton: CommandListener 만 (ReturnSubTree 와 모니터들은 Day 2).
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.common.command_listener import CommandListener


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_returning_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            CommandListener("CommandListener", ctx),
            # TODO Day 2: HardwareHealthMonitor, CollisionEventHandler, MapBoundaryMonitor, ReturnSubTree
        ],
    )
