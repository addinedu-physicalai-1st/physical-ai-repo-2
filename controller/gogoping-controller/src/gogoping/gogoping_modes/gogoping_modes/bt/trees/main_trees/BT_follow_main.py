"""FOLLOW state MainTree — 사람 추종 (구 ASSIST/follow).

body = FollowTrack — perception 의 /gogoping/tracking_state 를 blackboard(TARGET_*) 에
브리지(관측·표시). 실제 추종 제어(cmd_vel)는 follow_node 가 담당 — 본 트리는 FOLLOW
state 유지 + perception 반영.

FollowTrack 은 영구 RUNNING — task_done 자동 발화 안 함.
사용자가 cancel 또는 다른 task_request 로만 이탈.
"""
from __future__ import annotations

import py_trees

from ....context import Context
from ...behaviors.perception import FollowTrack
from ._shell import build_active_main_tree


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return build_active_main_tree(
        "MainTree[FOLLOW]", ctx,
        body=FollowTrack("FollowTrack", ctx),
        include_battery_low=True,
        include_map_boundary=True,
        include_hw_health=True,
        # FOLLOW 제외 — 사람 추종(REACTIVE)은 nav2 controller 를 안 거쳐 collision_monitor
        # 게이팅 대상이 아니고, 추종 중 사람을 장애물로 정지시키면 안 됨.
        include_collision=False,
        include_command_listener=True,
        task_body=True,
    )
