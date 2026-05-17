"""# STUB — BT_carry_sub.py placeholder.

진짜 carry sub tree (``blackboard.CARRY_MODE`` 값에 따라 manual/goto/follow 3-way 분기.
상세: ``docs/bt/trees/BT_carry_sub.md``) 작성 전 자리 채움.

본 stub: 30 tick (3초 @ TICK_HZ=10) RUNNING → SUCCESS. 진짜 carry+goto 가 목적지 도달
시 종료하는 의미와 동일 (유한 종료).
"""
from __future__ import annotations

from ._base import StubRunningThenSuccess


class StubCarry(StubRunningThenSuccess):
    """carry sub tree placeholder. STUB — bt/trees/sub_trees/BT_carry_sub.py 로 교체."""

    def __init__(self, running_ticks: int | None = None):
        super().__init__(name="StubCarry", running_ticks=running_ticks)
