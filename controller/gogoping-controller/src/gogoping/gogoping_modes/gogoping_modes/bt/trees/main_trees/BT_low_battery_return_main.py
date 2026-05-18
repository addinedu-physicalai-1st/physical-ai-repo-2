"""LOW_BATTERY_RETURN state MainTree — 배터리 자동 복귀 (사용자 명령 차단).

RETURNING 과 비교:
    RETURNING (사용자 명시 / idle_timeout)        LOW_BATTERY_RETURN (battery_low 자동)
    ─ HardwareHealthMonitor                       ─ HardwareHealthMonitor   (동일)
    ─ CollisionEventHandler                       ─ CollisionEventHandler   (동일)
    ─ MapBoundaryMonitor                          ─ MapBoundaryMonitor      (동일)
    ─ CommandListener  ★ 사용자 cancel 가능       ─ CommandListener 없음    ★ 차단
    ─ ReturnSubTree (NavTo → Align → ...)         ─ ReturnSubTree           (동일)

CommandListener 부재가 핵심 — 사용자가 SetGoal.srv 호출해도 받을 server 없음 → reconciler
가 거부 (current_state == LOW_BATTERY_RETURN 면 fsm_in_low_battery_return reason). 결국
robot 은 충전소 도달까지 일관 진행, 도착 시 docked → CHARGING.

lockdown 정책 정확히:
- *사용자 명령* 차단 (CommandListener 없음)
- *안전 monitor* 는 정상 배치 (MapBoundaryMonitor / HW / Collision) — 자율 ERROR 전이 가능

현재 배치: MapBoundaryMonitor + ReturnSubTree. HW / Collision monitor 는 추후.
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.common.map_boundary_monitor import MapBoundaryMonitor
from ..sub_trees.BT_return_sub import build_return_subtree


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_low_battery_return_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            MapBoundaryMonitor("MapBoundaryMonitor", ctx),
            build_return_subtree(ctx),
            # TODO 추후: HardwareHealthMonitor, CollisionEventHandler
        ],
    )
