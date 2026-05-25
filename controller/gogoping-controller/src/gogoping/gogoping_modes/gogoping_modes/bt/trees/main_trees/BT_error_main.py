"""ERROR state MainTree — terminal. 모터 즉시 정지.

ERROR 는 terminal state — 어떤 trigger 도 받지 않음. 사람이 robot 재시작해야 복구.
따라서 CommandListener 없음, monitor 없음. shell helper 사용 안 함 — 단순 1-child Parallel.

자식 (현재 단계):
  └─ StopAllMotors      (cmd_vel = 0 + torque OFF)

추후 추가 예정:
  ├─ NotifyAdminUI      (WebSocket alert)
  └─ LogErrorToDB       (error_log INSERT)
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.recovery.stop_all_motors import StopAllMotors


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="MainTree[ERROR]",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            StopAllMotors("StopAllMotors", ctx),
        ],
    )
