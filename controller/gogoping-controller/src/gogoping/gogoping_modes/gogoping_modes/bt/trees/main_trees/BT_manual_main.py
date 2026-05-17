"""MANUAL state MainTree — 토크 해제, 사용자가 직접 미는 모드.

현재 stub: CommandListener 만 (ManualTorqueHold 는 추후 — torque off
service 호출하려면 Vic Pinky base driver 의 service spec 확정 필요).

진짜 추후 모양 (``docs/bt/trees/BT_manual_main.md``):
    Parallel
      ├─ ManualTorqueHold  (추후 — initialise 에서 torque OFF, terminate 에서 ON 복원)
      └─ CommandListener   (추후 ✅)
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.common.command_listener import CommandListener


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_manual_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            # TODO 추후: ManualTorqueHold (가장 중요 — torque off 자체)
            CommandListener("CommandListener", ctx),
        ],
    )
