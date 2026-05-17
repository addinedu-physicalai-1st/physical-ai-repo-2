"""ERROR state MainTree — terminal. 모터 정지 + admin alert + log.

ERROR 는 **terminal state** — 어떤 trigger 도 받지 않음. 사람이 robot 재시작해야 복구.
따라서 CommandListener 없음 (받을 명령 없음).

Day 1 walking skeleton: 빈 Parallel (Day 2 에 안전 정지 시퀀스 추가).
Day 2 모양:
    Parallel
      └─ Sequence (1회 실행 후 SUCCESS, 그 후 root 는 무한 RUNNING 유지 의미 불명 — 재검토)
            ├─ StopAllMotors      (cmd_vel = 0)
            ├─ NotifyAdminUI      (WebSocket alert)
            └─ LogErrorToDB       (error_log INSERT)
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_error_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            # Day 1 walking skeleton — 자식 0개 (terminal idle).
            # Day 2 TODO: Sequence(StopAllMotors → NotifyAdminUI → LogErrorToDB)
        ],
    )
