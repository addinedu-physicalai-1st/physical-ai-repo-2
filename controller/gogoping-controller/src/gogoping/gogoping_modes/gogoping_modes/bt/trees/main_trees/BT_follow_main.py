"""FOLLOW state MainTree — 사람 추종 (구 ASSIST/follow).

현재: StubFollow body (실제 BT_follow_sub 미구현 — docs/bt/status.md follow 항목 ☐).
실제 SubTree 완성 시 import 교체.

StubFollow 는 StubInfiniteRunning — 영구 RUNNING. task_done 자동 발화 안 함.
사용자가 cancel 또는 다른 task_request 로만 이탈.
"""
from __future__ import annotations

import py_trees

from ....context import Context
from ...behaviors._stubs import StubFollow
from ._shell import build_active_main_tree


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return build_active_main_tree(
        "MainTree[FOLLOW]", ctx,
        body=StubFollow(),    # TODO: build_follow_subtree(ctx) 로 교체
        include_battery_low=True,
        include_map_boundary=True,
        include_hw_health=True,
        include_collision=True,
        include_command_listener=True,
        task_body=True,
    )
