"""# STUB — BT_hide_and_seek_sub.py placeholder.

진짜 hide-and-seek sub tree (1회 실행 후 종료. ``search_waypoints`` 리스트 길이에 따라
동적 빌드. 상세: ``docs/bt/trees/BT_hide_and_seek_sub.md`` + ``docs/conventions.md §4.1``)
작성 전 자리 채움.

본 stub: 30 tick (3초 @ TICK_HZ=10) RUNNING → SUCCESS. 진짜 hideseek 는 수십초 ~ 수분
이지만 stub 단계에선 시연용으로 짧게.
"""
from __future__ import annotations

from ._base import StubRunningThenSuccess


class StubHideseek(StubRunningThenSuccess):
    """hideseek sub tree placeholder. STUB — bt/trees/sub_trees/BT_hide_and_seek_sub.py 로 교체."""

    def __init__(self, running_ticks: int | None = None):
        super().__init__(name="StubHideseek", running_ticks=running_ticks)
