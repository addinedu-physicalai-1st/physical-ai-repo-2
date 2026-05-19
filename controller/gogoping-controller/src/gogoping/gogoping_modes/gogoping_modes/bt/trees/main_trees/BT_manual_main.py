"""MANUAL state MainTree — 토크 해제, 사용자가 직접 미는 모드.

자식 3개 (Parallel SuccessOnAll, synchronise=False):
  ├─ ManualTorqueHold     (✅ initialise=torque OFF, terminate=torque ON 복원)
  ├─ MapBoundaryMonitor   (✅ 맵 영역 벗어나면 ERROR — MANUAL 예외 배치)
  └─ CommandListener      (✅ assist/play/return_request 받아 state 전이)

MANUAL 의 monitor 정책 (``docs/bt/trees/BT_manual_main.md``):
- BatteryLowMonitor / HardwareHealthMonitor / CollisionEventHandler 미배치 — 사용자가
  직접 제어 중 자동 빼앗기 / 자율 fault 방지.
- MapBoundaryMonitor **만 예외적 배치** — 사용자가 들고 옮기다 맵 경계 넘으면 nav2 가
  path planning 불가하므로 즉시 ERROR 알림 필요.

torque 복원 보장:
- main.py 의 ``_build_tree_for_state`` 가 state 전이 시 ``tree.shutdown()`` 명시 호출
  → py_trees 가 자식 ``terminate()`` 전파 → ManualTorqueHold.terminate() 에서 enable_torque()
  호출. idempotent — 실패해도 다른 state 가 cmd_vel 발행 시 driver 가 자동 enable 시도
  (별도 안전망은 base_driver 측 책임).
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors.common.command_listener import CommandListener
from ...behaviors.common.map_boundary_monitor import MapBoundaryMonitor
from ...behaviors.manual.manual_torque_hold import ManualTorqueHold


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_manual_main",
        policy=ParallelPolicy.SuccessOnAll(synchronise=False),
        children=[
            ManualTorqueHold("ManualTorqueHold", ctx),
            MapBoundaryMonitor("MapBoundaryMonitor", ctx),
            CommandListener("CommandListener", ctx),
        ],
    )
