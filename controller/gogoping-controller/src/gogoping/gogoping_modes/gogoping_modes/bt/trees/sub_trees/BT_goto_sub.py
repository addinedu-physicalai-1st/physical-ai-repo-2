"""GOTO state MainTree (BT_goto_main) 의 body. NavigateToVertex + 도착 알림.

운반 시나리오는 user 가 FOLLOW + GOTO 를 순차 chain (composition).
이 SubTree 자체는 단일 이동 동작만 책임.

자세한 명세: docs/bt/trees/BT_goto_sub.md
"""
from __future__ import annotations

import py_trees
from py_trees.common import Access

from ....context import Context
from ...behaviors.common.ui_publish import UIPublish
from ...behaviors.navigation.navigate_to_vertex import NavigateToVertex
from ...blackboard import Keys


_ARRIVAL_MSG = {"event": "announce", "text": "도착했습니다"}
_DEFAULT_DESTINATION = "복도"   # force_state(GOTO) fallback (운동장 제거됨 → 복도로 변경)


def build_goto_subtree(ctx: Context) -> py_trees.behaviour.Behaviour:
    """name="BT_goto_sub" — tree_inspector 의 BT_*_sub 패턴 매칭 → admin UI BT SUB 영역 표시.

    2026-05-28: DESTINATION_KEY 가 비었으면 _DEFAULT_DESTINATION 으로 fallback
    (force_state debug 진입 시 즉시 Failure → return_request 자동 도피 방지).
    """
    # build 시점에 fallback — blackboard 가 비었거나 키 없으면 default 채움
    try:
        bb = py_trees.blackboard.Client(name="BT_goto_sub/builder")
        bb.register_key(key=Keys.DESTINATION_KEY, access=Access.WRITE)
        try:
            cur = bb.get(Keys.DESTINATION_KEY)
        except KeyError:
            cur = ""
        if not cur:
            bb.set(Keys.DESTINATION_KEY, _DEFAULT_DESTINATION)
    except Exception:
        pass

    return py_trees.composites.Sequence(
        name="BT_goto_sub",
        memory=True,
        children=[
            NavigateToVertex(target_key=Keys.DESTINATION_KEY),
            UIPublish("AnnounceArrival", ctx, message=_ARRIVAL_MSG),
        ],
    )
