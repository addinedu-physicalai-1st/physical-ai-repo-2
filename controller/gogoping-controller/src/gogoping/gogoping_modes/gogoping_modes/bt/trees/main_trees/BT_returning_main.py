"""RETURNING state MainTree — 도크로 자율 복귀 중.

Parallel 자식:
- BatteryLowMonitor — escalation 용 (RETURNING 중 배터리 더 떨어지면 LOW_BATTERY_RETURN)
- MapBoundaryMonitor — 맵 밖 나가면 fault → ERROR
- HardwareHealthMonitor — LIDAR/odom staleness → fault → ERROR
- CommandListener — 사용자 cancel / 다른 명령 수신
- ReturnSubTree — 실제 복귀 동작 (NavigateToVertex → AlignToDock → ReverseIntoDock)

ReturnSubTree 가 SUCCESS 하면 robot 은 도크에 들어간 상태로 cmd_vel=0. 자동 `docked`
trigger 는 발표 범위 외 — 사람이 admin UI 디버그 버튼으로 발사 → CHARGING.

추후 추가: CollisionEventHandler.
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.common.battery_low_monitor import BatteryLowMonitor
from ...behaviors.common.command_listener import CommandListener
from ...behaviors.common.hardware_health_monitor import HardwareHealthMonitor
from ...behaviors.common.map_boundary_monitor import MapBoundaryMonitor
from ..sub_trees.BT_return_sub import build_return_subtree


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_returning_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            BatteryLowMonitor("BatteryLowMonitor", ctx),
            MapBoundaryMonitor("MapBoundaryMonitor", ctx),
            HardwareHealthMonitor("HardwareHealthMonitor", ctx),
            CommandListener("CommandListener", ctx),
            build_return_subtree(ctx),
            # TODO 추후: CollisionEventHandler
        ],
    )
