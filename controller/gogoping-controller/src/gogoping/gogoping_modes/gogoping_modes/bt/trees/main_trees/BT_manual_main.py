"""MANUAL state MainTree — 토크 해제, 사용자가 직접 미는 모드.

현재 stub: CommandListener + MapBoundaryMonitor (ManualTorqueHold 는 추후 — torque off
service 호출하려면 Vic Pinky base driver 의 service spec 확정 필요).

MANUAL 의 monitor 정책 (``docs/bt/trees/BT_manual_main.md``):
- BatteryLowMonitor / HardwareHealthMonitor / CollisionEventHandler 미배치 — 사용자가
  직접 제어 중 자동 빼앗기 / 자율 fault 방지.
- MapBoundaryMonitor **만 예외적 배치** — 사용자가 들고 옮기다 맵 경계 넘으면 nav2 가
  path planning 불가하므로 즉시 ERROR 알림 필요.

진짜 추후 모양:
    Parallel
      ├─ ManualTorqueHold     (추후 — initialise 에서 torque OFF, terminate 에서 ON 복원)
      ├─ MapBoundaryMonitor   (✅)
      └─ CommandListener      (✅)
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.common.command_listener import CommandListener
from ...behaviors.common.map_boundary_monitor import MapBoundaryMonitor


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_manual_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            # TODO 추후: ManualTorqueHold (가장 중요 — torque off 자체)
            MapBoundaryMonitor("MapBoundaryMonitor", ctx),
            CommandListener("CommandListener", ctx),
        ],
    )
