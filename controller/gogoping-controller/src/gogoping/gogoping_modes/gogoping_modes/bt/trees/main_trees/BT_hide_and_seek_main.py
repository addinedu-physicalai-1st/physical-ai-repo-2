"""HIDEANDSEEK state MainTree — 숨바꼭질 (구 PLAY/hideseek).

body: BT_hide_and_seek_sub — 현재 patrol-only 구현 (docs/bt/status.md).
search_waypoints 순회 후 SUCCESS → task_done → IDLE.

(추후 실제 FOUND 감지 구현 예정. 현재는 patrol 완료 = 게임 종료.)
"""
from __future__ import annotations

import py_trees

from ....context import Context
from ..sub_trees.BT_hide_and_seek_sub import build_hide_and_seek_sub
from ._shell import build_active_main_tree


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return build_active_main_tree(
        "MainTree[HIDEANDSEEK]", ctx,
        body=build_hide_and_seek_sub(ctx),
        include_battery_low=True,
        include_map_boundary=True,
        include_hw_health=True,
        include_collision=True,
        include_proximity=True,
        include_command_listener=True,
        task_body=True,
    )
