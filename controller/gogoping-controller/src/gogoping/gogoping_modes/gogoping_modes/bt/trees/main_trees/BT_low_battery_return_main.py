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

현재 stub: monitor 들 + ReturnSubTree 모두 추후 구현. 현재는 빈 Parallel
(CommandListener 도 없고 monitor 도 없음 → 사실상 idle BT). main.py 의 spin 이 계속 tick
하므로 docked trigger 가 외부 (BatterySubscriber ) 에서 발화될 때까지 가만히 있음.
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_low_battery_return_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            # 현재 단계 — 자식 0개 (idle).
            # TODO:
            #   HardwareHealthMonitor, CollisionEventHandler, MapBoundaryMonitor,
            #   ReturnSubTree (NavTo charging_dock_approach_key → AlignToDock →
            #                  ApproachDock → VerifyDockingContact)
        ],
    )
