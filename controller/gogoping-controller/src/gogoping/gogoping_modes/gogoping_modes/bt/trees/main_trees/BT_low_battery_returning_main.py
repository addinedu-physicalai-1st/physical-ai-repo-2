"""LOW_BATTERY_RETURNING state MainTree — 배터리 긴급 복귀 lockdown.

monitor 정책 (state-bt.md):
- MapBoundaryMonitor     ✅
- HardwareHealthMonitor  ✅
- BatteryLowMonitor      ❌ (이미 자기가 결과물)
- CommandListener        ❌ (lockdown)

body: BT_return_sub — RETURNING 과 동일 sub_tree 재사용.
"""
from __future__ import annotations

import py_trees

from ....context import Context
from ..sub_trees.BT_return_sub import build_return_subtree
from ._shell import build_active_main_tree


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return build_active_main_tree(
        "MainTree[LOW_BATTERY_RETURNING]", ctx,
        body=build_return_subtree(ctx),
        include_battery_low=False,
        include_map_boundary=True,
        include_hw_health=True,
        include_collision=True,
        include_proximity=True,
        include_command_listener=False,
        task_body=False,
    )
