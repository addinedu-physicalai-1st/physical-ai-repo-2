"""ERROR state MainTree — 모터 정지 + admin alert + log + reset 대기.

Day 1 walking skeleton: CommandListener 만 (reset 명령만 valid).
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.common.command_listener import CommandListener


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_error_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            CommandListener("CommandListener", ctx),
            # TODO Day 2: Sequence(StopAllMotors → NotifyAdminUI → LogErrorToDB)
        ],
    )
