"""ASSIST state MainTree — 교사 보조 (carry / follow / lullaby).

현재 stub: CommandListener + TaskSelector (stub 자식들).
추후: 배터리/HW/충돌/맵바운더리 monitor 추가.
추후: stub 4개를 진짜 SubTree 호출로 교체.

TaskSelector 동작:
    blackboard.assist_task == "carry"   → CheckTask("carry")    SUCCESS → StubCarry
    blackboard.assist_task == "follow"  → CheckTask("follow")   SUCCESS → StubFollow
    blackboard.assist_task == "lullaby" → CheckTask("lullaby")  SUCCESS → StubLullaby

Selector(memory=False) — 매 tick assist_task 다시 평가 → mode 변경 즉시 반영.
"""
from __future__ import annotations

import py_trees
from py_trees.common import ParallelPolicy

from ....context import Context
from ...behaviors._stubs import StubCarry, StubFollow, StubLullaby
from ...behaviors.common.battery_low_monitor import BatteryLowMonitor
from ...behaviors.common.check_task import CheckTask
from ...behaviors.common.command_listener import CommandListener
from ...blackboard import Keys


def _task_selector(ctx: Context) -> py_trees.behaviour.Behaviour:
    """3 task 분기 Selector — assist_task 값으로 branch 선택."""
    return py_trees.composites.Selector(
        name="TaskSelector",
        memory=False,
        children=[
            py_trees.composites.Sequence(
                name="carry_branch", memory=True,
                children=[
                    CheckTask(Keys.ASSIST_TASK, "carry"),
                    StubCarry(),    # STUB with build_carry(ctx)
                ],
            ),
            py_trees.composites.Sequence(
                name="follow_branch", memory=True,
                children=[
                    CheckTask(Keys.ASSIST_TASK, "follow"),
                    StubFollow(),   # STUB with build_follow(ctx)
                ],
            ),
            py_trees.composites.Sequence(
                name="lullaby_branch", memory=True,
                children=[
                    CheckTask(Keys.ASSIST_TASK, "lullaby"),
                    StubLullaby(),  # STUB with build_lullaby(ctx)
                ],
            ),
        ],
    )


def build(ctx: Context) -> py_trees.behaviour.Behaviour:
    return py_trees.composites.Parallel(
        name="BT_assist_main",
        # SuccessOnSelected — TaskSelector 가 SUCCESS 면 root SUCCESS (task 완료 → IDLE 복귀)
        policy=ParallelPolicy.SuccessOnSelected(
            children=[_task_selector(ctx)],  # placeholder — 아래 children 의 같은 인스턴스
            synchronise=False,
        ),
        children=[],  # 아래에서 다시 채움 (policy 의 children 과 instance 일치)
    ).__class__(
        # 위 trick 이 깔끔하지 않아서 재작성 — 명시적으로:
        name="BT_assist_main",
        policy=None,  # 아래에서 재설정
    ) if False else _build_assist_root(ctx)


def _build_assist_root(ctx: Context) -> py_trees.behaviour.Behaviour:
    """SuccessOnSelected 의 children 과 root.children 이 *동일 인스턴스* 여야
    py_trees 가 인식. 한번에 만든다."""
    task_sel = _task_selector(ctx)
    return py_trees.composites.Parallel(
        name="BT_assist_main",
        policy=ParallelPolicy.SuccessOnSelected(children=[task_sel], synchronise=False),
        children=[
            BatteryLowMonitor("BatteryLowMonitor", ctx),
            CommandListener("CommandListener", ctx),
            task_sel,
            # TODO 추후: HardwareHealthMonitor, CollisionEventHandler, MapBoundaryMonitor
        ],
    )
