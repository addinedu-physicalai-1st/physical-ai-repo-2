"""# STUB: replace Day 3~4 — Day 1 walking skeleton placeholder behaviors.

진짜 BT_*_sub 트리가 작성되는 Day 3~4 에 본 폴더 통째로 삭제 + 사용처 4 군데 교체.
``grep -r "STUB:" controller/gogoping-controller/`` 로 한 번에 찾을 수 있다.
"""
from __future__ import annotations

from ._base import StubRunningThenSuccess
from .stub_carry import StubCarry
from .stub_follow import StubFollow
from .stub_hideseek import StubHideseek
from .stub_lullaby import StubLullaby

__all__ = [
    "StubCarry",
    "StubFollow",
    "StubHideseek",
    "StubLullaby",
    "StubRunningThenSuccess",
]
