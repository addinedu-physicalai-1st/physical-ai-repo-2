"""ERROR state MainTree — terminal. 모터 즉시 정지 + admin alert + log.

ERROR 는 **terminal state** — 어떤 trigger 도 받지 않음. 사람이 robot 재시작해야 복구.
따라서 CommandListener 없음 (받을 명령 없음).

자식 (현재 단계):
  └─ StopAllMotors      (cmd_vel = 0 + torque OFF)

추후 추가 예정 (Sequence 로 확장):
  └─ Sequence
        ├─ StopAllMotors      (✅ 1회 cmd_vel=0 + torque OFF)
        ├─ NotifyAdminUI      (WebSocket alert — admin UI 의 ERROR overlay)
        └─ LogErrorToDB       (error_log INSERT — blackboard ERROR_REASON / ERROR_SOURCE)

ERROR 가 terminal 이라 root 가 어떤 status 리턴해도 BT swap 안 일어남.
StopAllMotors 가 SUCCESS 리턴 후 Parallel 이 SUCCESS — 그 후 tick 도 의미 없음.
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.recovery.stop_all_motors import StopAllMotors


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_error_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            StopAllMotors("StopAllMotors", ctx),
        ],
    )
