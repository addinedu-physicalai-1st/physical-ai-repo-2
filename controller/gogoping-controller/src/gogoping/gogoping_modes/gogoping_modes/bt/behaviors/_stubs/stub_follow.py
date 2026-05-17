"""# STUB — BT_follow_sub.py placeholder.

진짜 follow sub tree (정상 모드 + Loss Recovery 2-phase. 상세: ``docs/bt/trees/
BT_follow_sub.md``) 작성 전 자리 채움.

본 stub: **무한 RUNNING** — 진짜 follow 가 사람이 사라지지 않는 한 계속 RUNNING 인
것과 의미상 동일. cancel / battery_low / fault 만 종료시킴.
"""
from __future__ import annotations

from ._base import StubInfiniteRunning


class StubFollow(StubInfiniteRunning):
    """follow sub tree placeholder. STUB — bt/trees/sub_trees/BT_follow_sub.py 로 교체."""

    def __init__(self):
        super().__init__(name="StubFollow")
