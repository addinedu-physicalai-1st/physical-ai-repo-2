"""PLAY state MainTree — 아이 놀이 (hideseek).

CommandListener + TaskSelector(hideseek). hideseek 은 현재 patrol building block 만
호출 — 진짜 hideseek 확장은 BT_hide_and_seek_sub.py 안에서.
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.common.battery_low_monitor import BatteryLowMonitor
from ...behaviors.common.check_task import CheckTask
from ...behaviors.common.command_listener import CommandListener
from ...behaviors.common.hardware_health_monitor import HardwareHealthMonitor
from ...behaviors.common.map_boundary_monitor import MapBoundaryMonitor
from ...blackboard import Keys
from ..sub_trees.BT_hide_and_seek_sub import build_hide_and_seek_sub


def _task_selector(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Selector(
        name="TaskSelector",
        memory=False,
        children=[
            py_trees.composites.Sequence(
                name="hideseek_branch", memory=True,
                children=[
                    CheckTask(Keys.PLAY_TASK, "hideseek"),
                    build_hide_and_seek_sub(ctx),
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
            BatteryLowMonitor("BatteryLowMonitor", ctx),
            MapBoundaryMonitor("MapBoundaryMonitor", ctx),
            HardwareHealthMonitor("HardwareHealthMonitor", ctx),
            CommandListener("CommandListener", ctx),
            task_sel,
            # TODO 추후: CollisionEventHandler
        ],
    )
