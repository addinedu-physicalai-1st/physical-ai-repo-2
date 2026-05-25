"""LULLABY state MainTree — 자장가 재생 (구 ASSIST/lullaby).

body: BT_lullaby_sub — 단일 LullabyAudio leaf. initialise=publish lullaby_play,
update=영구 RUNNING, terminate=publish lullaby_stop.

영구 RUNNING 이라 root 가 SUCCESS 되지 않음 — task_done 자동 발화 안 함.
사용자가 cancel 또는 다른 task_request 로만 이탈.
"""
from __future__ import annotations

import py_trees

from ....context import Context
from ..sub_trees.BT_lullaby_sub import build_lullaby_subtree
from ._shell import build_active_main_tree


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return build_active_main_tree(
        "MainTree[LULLABY]", ctx,
        body=build_lullaby_subtree(ctx),
        include_battery_low=True,
        include_map_boundary=True,
        include_hw_health=True,
        include_collision=True,
        include_command_listener=True,
        task_body=True,
    )
