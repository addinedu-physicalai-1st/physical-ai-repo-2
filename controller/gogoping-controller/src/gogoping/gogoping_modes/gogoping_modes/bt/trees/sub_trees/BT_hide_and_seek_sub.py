"""BT_hide_and_seek_sub — 숨바꼭질 sub tree (현재: patrol 만).

흐름:
    1. blackboard 의 ``search_waypoints`` 를 읽음
    2. ``build_patrol_sub(ctx, wps)`` 호출 → vertex 순회 + 카메라 sweep

빈 리스트 / 결손 시 ``Failure`` leaf 반환 (정상 경로에선 reconciler 가
``missing_search_waypoints`` 로 미리 차단 — ForceState 디버그 우회 시 방어).

진짜 hideseek (아이 인식 / FOUND 처리 / target_id 매칭) 은 추후 확장. 본 빌더는
*building block* — ``BT_play_main`` 의 hideseek_branch 에서 호출됨.

자세한 명세: docs/bt/trees/BT_hide_and_seek_sub.md
"""
from __future__ import annotations

import py_trees
from py_trees.common import Access

from ....context import Context
from ...blackboard import Keys
from .BT_patrol_sub import build_patrol_sub


def build_hide_and_seek_sub(ctx: Context) -> py_trees.behaviour.Behaviour:
    """blackboard.search_waypoints 를 읽어 patrol sub 트리 반환.

    Parameters
    ----------
    ctx : Context
        ``ctx.camera_pan`` 사용 (PanCameraSweep 안에서).

    Returns
    -------
    Behaviour
        정상: ``build_patrol_sub`` 결과 (vertex N 개 순회 Sequence).
        빈 리스트 / 결손: ``Failure`` leaf
        (이름 ``BT_hide_and_seek_sub_no_waypoints``) — task selector 가 fail.
    """
    bb = py_trees.blackboard.Client(name="BT_hide_and_seek_sub/builder")
    bb.register_key(key=Keys.SEARCH_WAYPOINTS, access=Access.READ)
    try:
        raw = bb.get(Keys.SEARCH_WAYPOINTS)
    except KeyError:
        # init_blackboard 미호출 / Blackboard.clear 우회 — 디버그 환경에서만 발생.
        raw = None
    wps = list(raw or [])

    if not wps:
        return py_trees.behaviours.Failure(name="BT_hide_and_seek_sub_no_waypoints")

    return build_patrol_sub(ctx, wps)
