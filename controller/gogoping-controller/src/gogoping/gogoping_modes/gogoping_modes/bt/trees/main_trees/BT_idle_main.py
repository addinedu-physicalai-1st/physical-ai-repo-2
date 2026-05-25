"""IDLE state MainTree — 명령 대기.

monitor 정책 (state-bt.md):
- BatteryLowMonitor      ✅
- IdleTimeoutMonitor     ✅ (IDLE 만)
- MapBoundaryMonitor     ✅
- HardwareHealthMonitor  ✅
- CommandListener        ✅

body 없음 — 명령 대기만. 시간 흘러 idle_timeout 발화하면 RETURNING.
"""
from __future__ import annotations

import py_trees

from ....context import Context
from ._shell import build_active_main_tree


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return build_active_main_tree(
        "MainTree[IDLE]", ctx,
        body=py_trees.behaviours.Running(name="IdleHold"),   # 영구 RUNNING, root 가 SuccessOnAll
        include_battery_low=True,
        include_idle_timeout=True,
        include_map_boundary=True,
        include_hw_health=True,
        include_collision=False,
        include_command_listener=True,
        task_body=False,
    )
