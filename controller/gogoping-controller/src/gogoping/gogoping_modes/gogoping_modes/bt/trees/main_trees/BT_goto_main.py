"""GOTO state MainTree — 지정 vertex 로 이동 (구 ASSIST/goto).

body: BT_goto_sub — Sequence(NavigateToVertex(destination_key) + UIPublish("도착했습니다"))
SUCCESS 시 root SUCCESS → main.py 가 task_done 발화 → IDLE.

monitor 정책 (state-bt.md): battery_low / map_boundary / hw_health / collision / command_listener 전부 ON.
"""
from __future__ import annotations

import py_trees

from ....context import Context
from ..sub_trees.BT_goto_sub import build_goto_subtree
from ._shell import build_active_main_tree


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return build_active_main_tree(
        "MainTree[GOTO]", ctx,
        body=build_goto_subtree(ctx),
        include_battery_low=True,
        include_map_boundary=True,
        include_hw_health=True,
        include_collision=True,
        include_proximity=True,
        include_command_listener=True,
        task_body=True,
    )
