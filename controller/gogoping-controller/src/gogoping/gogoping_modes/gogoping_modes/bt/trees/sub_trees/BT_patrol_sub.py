"""BT_patrol_sub — vertex 목록을 순서대로 돌며 각 vertex 에서 카메라 sweep.

빌드 시 ``waypoints`` 인자 (list[str]) 를 받아 vertex 마다 ``visit_<name>`` Sequence 를
동적으로 생성:

    visit_<name>:
        ├─ SetPatrolIndex(i)     → BB.patrol_current_index = i (admin UI 시각화용)
        ├─ SelectVertex          → BB.target_vertex_name = <name>
        ├─ NavigateToVertex      → graph_router 호출
        ├─ BrakeAndWait          → cmd_vel=0 publish + 0.5s 대기 (잔여 관성 정리)
        └─ PanCameraSweep        → 90 → 30 → 150 → 90

마지막 자식으로 ``SetPatrolIndex(len(waypoints))`` 추가 — 모든 vertex 완료 표시.

각 visit Sequence 는 ``FailureIsSuccess`` decorator 로 감싸 한 vertex 실패가 전체 중단을
일으키지 않게 함 (skip-on-failure 정책).

본 빌더는 *building block* — FSM trigger / TaskSelector 결선은 별도 (호출자가 책임).
일반 호출자가 빌드 후 main_tree 에 삽입한다. 단독 단위 테스트도 가능.

자세한 명세: docs/bt/trees/BT_patrol_sub.md (작성 예정)
"""
from __future__ import annotations

from typing import Sequence as _Seq

import py_trees
from py_trees.decorators import FailureIsSuccess

from ....context import Context
from ...behaviors.common.select_vertex import SelectVertex
from ...behaviors.common.set_patrol_index import SetPatrolIndex
from ...behaviors.follow.pan_camera_sweep import PanCameraSweep
from ...behaviors.navigation.brake_and_wait import BrakeAndWait
from ...behaviors.navigation.navigate_to_vertex import NavigateToVertex


def build_patrol_sub(
    ctx: Context,
    waypoints: _Seq[str],
) -> py_trees.behaviour.Behaviour:
    """vertex N 개 순회 sub tree.

    Parameters
    ----------
    ctx : Context
        ``ctx.camera_pan`` 사용 (PanCameraSweep 안에서).
    waypoints : Sequence[str]
        순회할 vertex 이름 list. 빈 list 거부 (ValueError).

    Returns
    -------
    Behaviour
        ``Sequence("BT_patrol_sub", memory=True)`` — vertex 마다
        ``FailureIsSuccess(Sequence("visit_<name>", ...))`` 자식.

    Raises
    ------
    ValueError
        waypoints 가 비었거나 빈 문자열을 포함하는 경우.
    """
    names = [str(n) for n in waypoints]
    if not names:
        raise ValueError("build_patrol_sub: waypoints must be non-empty")
    for n in names:
        if not n:
            raise ValueError("build_patrol_sub: waypoints contains empty name")

    children: list[py_trees.behaviour.Behaviour] = []
    for i, name in enumerate(names):
        visit = py_trees.composites.Sequence(
            name=f"visit_{name}",
            memory=True,
            children=[
                SetPatrolIndex(name=f"set_index_{i}", index=i),
                SelectVertex(name=f"select_{name}", vertex_name=name),
                NavigateToVertex(name=f"nav_{name}"),
                BrakeAndWait(name=f"brake_{name}", context=ctx),
                PanCameraSweep(name=f"sweep_{name}", context=ctx),
            ],
        )
        # 한 vertex 실패 시 다음 vertex 계속 — root Sequence 가 멈추지 않도록.
        children.append(FailureIsSuccess(name=f"safe_visit_{name}", child=visit))

    # 모든 vertex 완료 표시 — index = N (admin UI 가 X 모두 그리도록)
    children.append(SetPatrolIndex(name="set_index_done", index=len(names)))

    return py_trees.composites.Sequence(
        name="BT_patrol_sub",
        memory=True,
        children=children,
    )
