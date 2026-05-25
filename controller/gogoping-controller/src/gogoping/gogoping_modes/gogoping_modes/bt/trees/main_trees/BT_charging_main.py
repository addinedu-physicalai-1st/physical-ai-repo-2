"""CHARGING state MainTree — 도크에서 충전 중.

monitor 정책 (state-bt.md):
- BatteryFullMonitor     ✅ (≥70% → battery_full → IDLE)
- MapBoundaryMonitor     ✅
- HardwareHealthMonitor  ✅
- CommandListener        ✅
- (battery_low 없음 — 이미 충전 중)

부팅 직후 CHARGING → IDLE 전이 자동화 — BatterySubscriber 의 init 값이 100.0 이라 첫 tick 에 fire.
"""
from __future__ import annotations

import py_trees

from ....context import Context
from ._shell import build_active_main_tree


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return build_active_main_tree(
        "MainTree[CHARGING]", ctx,
        body=py_trees.behaviours.Running(name="ChargingHold"),
        include_battery_full=True,
        include_battery_low=False,
        include_map_boundary=True,
        include_hw_health=True,
        include_collision=False,
        include_command_listener=True,
        task_body=False,
    )
