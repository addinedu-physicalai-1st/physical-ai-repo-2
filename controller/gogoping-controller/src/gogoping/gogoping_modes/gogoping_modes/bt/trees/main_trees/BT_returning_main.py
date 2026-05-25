"""RETURNING state MainTree — 도크 복귀.

monitor 정책 (state-bt.md):
- BatteryLowMonitor      ✅ (escalation → LOW_BATTERY_RETURNING)
- MapBoundaryMonitor     ✅
- HardwareHealthMonitor  ✅
- CommandListener        ✅ (cancel / 새 task 받음)

body: BT_return_sub — OneShot(Sequence(NavigateToVertex → AlignToDock → ReverseIntoDock → VerifyDockingContact))
VerifyDockingContact 가 docked trigger 자체 발사 → CHARGING.
"""
from __future__ import annotations

import py_trees

from ....context import Context
from ..sub_trees.BT_return_sub import build_return_subtree
from ._shell import build_active_main_tree


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return build_active_main_tree(
        "MainTree[RETURNING]", ctx,
        body=build_return_subtree(ctx),
        include_battery_low=True,
        include_map_boundary=True,
        include_hw_health=True,
        include_collision=True,
        include_command_listener=True,
        task_body=False,    # docked trigger 가 별도 — root SUCCESS 시 task_done 발화 X
    )
