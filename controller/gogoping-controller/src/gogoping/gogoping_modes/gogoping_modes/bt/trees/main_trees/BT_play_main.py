"""PLAY state MainTree — 아이 놀이 (hideseek).

Day 1 walking skeleton: CommandListener + TaskSelector(hideseek stub).
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors._stubs import StubHideseek
from ...behaviors.common.check_task import CheckTask
from ...behaviors.common.command_listener import CommandListener
from ...blackboard import Keys


def _task_selector(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Selector(
        name="TaskSelector",
        memory=False,
        children=[
            py_trees.composites.Sequence(
                name="hideseek_branch", memory=True,
                children=[
                    CheckTask(Keys.PLAY_TASK, "hideseek"),
                    StubHideseek(),  # STUB: replace Day 3~4 with build_hide_and_seek(ctx)
                ],
            ),
        ],
    )


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    task_sel = _task_selector(ctx)
    return py_trees.composites.Parallel(
        name="BT_play_main",
        policy=ParallelPolicy.SuccessOnSelected(children=[task_sel], synchronise=False),
        children=[
            CommandListener("CommandListener", ctx),
            task_sel,
            # TODO Day 2: monitors
        ],
    )
