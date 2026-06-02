"""MainTree 공통 monitor shell.

10 MainTree 가 모두 "Parallel(monitors + body)" 패턴. 모니터 구성을 helper 한 곳으로
모으고 per-state 정책은 flag 로 표현 — `state-bt.md` 의 monitor 매트릭스가 코드에 명시.

task state (GOTO/FOLLOW/LULLABY/HIDEANDSEEK) 는 body SUCCESS 시 root SUCCESS 가
되어야 main.py 의 _on_tree_success 가 task_done trigger 발화. 따라서 task_body=True 면
SuccessOnSelected(children=[body]).

기타 active state (IDLE/CHARGING/MANUAL/RETURNING/LOW_BATTERY_RETURNING/ERROR) 는
SuccessOnAll — root 가 SUCCESS 되어도 main.py 가 별도 trigger 발화 안 함 (해당 state 전이는
monitor 가 trigger 함).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees
from py_trees.common import ParallelPolicy

from ...behaviors.common.battery_full_monitor import BatteryFullMonitor
from ...behaviors.common.battery_low_monitor import BatteryLowMonitor
from ...behaviors.common.collision_monitor import CollisionMonitor
from ...behaviors.common.command_listener import CommandListener
from ...behaviors.common.hardware_health_monitor import HardwareHealthMonitor
from ...behaviors.common.idle_timeout_monitor import IdleTimeoutMonitor
from ...behaviors.common.map_boundary_monitor import MapBoundaryMonitor
from ...behaviors.common.proximity_safety_monitor import ProximitySafetyMonitor

if TYPE_CHECKING:
    from ....context import Context


def build_active_main_tree(
    name: str,
    ctx: "Context",
    body: py_trees.behaviour.Behaviour,
    *,
    include_battery_full: bool = False,
    include_battery_low: bool = True,
    include_idle_timeout: bool = False,
    include_map_boundary: bool = True,
    include_hw_health: bool = True,
    include_collision: bool = True,    # TODO 추후 CollisionMonitor wiring
    include_proximity: bool = False,   # 사람/벽 근접 관측 leaf (graph_router 주행 트리만)
    include_command_listener: bool = True,
    task_body: bool = False,
) -> py_trees.behaviour.Behaviour:
    """state 별 monitor shell 을 가진 Parallel root 빌더.

    Parameters
    ----------
    name : str
        Parallel 노드 이름 — 일반적으로 ``"MainTree[<STATE>]"``.
    ctx : Context
        Behavior DI 의 표준 인자.
    body : Behaviour
        state 의 핵심 행동. task state 면 SubTree (BT_goto_sub 등), 시스템 state 면
        고유 노드 (ManualTorqueHold / StopAllMotors 등).
    include_* : bool
        monitor 별 on/off. ``state-bt.md`` 의 매트릭스 참조.
    task_body : bool
        True 면 policy=SuccessOnSelected(children=[body]) — body SUCCESS → root SUCCESS.
        task_done trigger 가 main.py._on_tree_success 에서 발화하도록 함.
        False 면 SuccessOnAll (root SUCCESS 가 별 의미 없음).
    """
    children: list[py_trees.behaviour.Behaviour] = []

    if include_battery_full:
        children.append(BatteryFullMonitor("BatteryFullMonitor", ctx))
    if include_battery_low:
        children.append(BatteryLowMonitor("BatteryLowMonitor", ctx))
    if include_idle_timeout:
        children.append(IdleTimeoutMonitor("IdleTimeoutMonitor", ctx))
    if include_map_boundary:
        children.append(MapBoundaryMonitor("MapBoundaryMonitor", ctx))
    if include_hw_health:
        children.append(HardwareHealthMonitor("HardwareHealthMonitor", ctx))
    if include_collision:
        children.append(CollisionMonitor("CollisionMonitor", ctx))
    if include_proximity:
        children.append(ProximitySafetyMonitor("ProximitySafetyMonitor", ctx))
    if include_command_listener:
        children.append(CommandListener("CommandListener", ctx))

    children.append(body)

    if task_body:
        policy = ParallelPolicy.SuccessOnSelected(children=[body], synchronise=False)
    else:
        policy = ParallelPolicy.SuccessOnAll(synchronise=False)

    return py_trees.composites.Parallel(name=name, policy=policy, children=children)


__all__ = ["build_active_main_tree"]
