"""GOTO state MainTree (BT_goto_main) 의 body. NavigateToVertex + 도착 알림.

운반 시나리오는 user 가 FOLLOW + GOTO 를 순차 chain (composition).
이 SubTree 자체는 단일 이동 동작만 책임.

자세한 명세: docs/bt/trees/BT_goto_sub.md
"""
from __future__ import annotations

import py_trees

from ....context import Context
from ...behaviors.common.ui_publish import UIPublish
from ...behaviors.navigation.navigate_to_vertex import NavigateToVertex
from ...blackboard import Keys


_ARRIVAL_MSG = {"event": "announce", "text": "도착했습니다"}


def build_goto_subtree(ctx: Context) -> py_trees.behaviour.Behaviour:
    """name="BT_goto_sub" — tree_inspector 의 BT_*_sub 패턴 매칭 → admin UI BT SUB 영역 표시."""
    return py_trees.composites.Sequence(
        name="BT_goto_sub",
        memory=True,
        children=[
            NavigateToVertex(target_key=Keys.DESTINATION_KEY),
            UIPublish("AnnounceArrival", ctx, message=_ARRIVAL_MSG),
        ],
    )
