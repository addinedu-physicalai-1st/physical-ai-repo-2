"""MANUAL state MainTree — 토크 해제, 사용자가 직접 미는 모드.

monitor 정책 (state-bt.md, BT_manual_main.md):
- ManualTorqueHold       ✅ (body — initialise=torque OFF, terminate=torque ON)
- MapBoundaryMonitor     ✅ (예외 — 사용자가 들고 옮기다 맵 경계 넘으면 ERROR)
- CommandListener        ✅
- BatteryLowMonitor      ❌ (자동 빼앗기 방지)
- HardwareHealthMonitor  ❌
- CollisionMonitor       ❌
- IdleTimeoutMonitor     ❌

torque 복원: tree.shutdown() → ManualTorqueHold.terminate() 에서 enable_torque() 보장.
"""
from __future__ import annotations

import py_trees

from ....context import Context
from ...behaviors.manual.manual_torque_hold import ManualTorqueHold
from ._shell import build_active_main_tree


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return build_active_main_tree(
        "MainTree[MANUAL]", ctx,
        body=ManualTorqueHold("ManualTorqueHold", ctx),
        include_battery_full=False,
        include_battery_low=False,
        include_idle_timeout=False,
        include_map_boundary=True,
        include_hw_health=False,
        include_collision=False,
        include_command_listener=True,
        task_body=False,
    )
