"""# STUB — BT_lullaby_sub.py placeholder.

진짜 lullaby sub tree (UI 가 mp3 재생, BT 는 종료 신호 대기. 상세: ``docs/bt/trees/
BT_lullaby_sub.md``) 작성 전 자리 채움.

본 stub: **무한 RUNNING** — 진짜 lullaby 가 사용자 stop 명령까지 RUNNING 인 것과
의미상 동일. cancel / 다른 mode 클릭 시 종료.
"""
from __future__ import annotations

from ._base import StubInfiniteRunning


class StubLullaby(StubInfiniteRunning):
    """lullaby sub tree placeholder. STUB — bt/trees/sub_trees/BT_lullaby_sub.py 로 교체."""

    def __init__(self):
        super().__init__(name="StubLullaby")
