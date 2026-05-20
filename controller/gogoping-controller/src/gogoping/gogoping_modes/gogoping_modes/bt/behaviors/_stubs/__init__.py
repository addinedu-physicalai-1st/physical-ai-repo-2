"""# STUB — 현재 단계 placeholder behaviors.

진짜 BT_*_sub 트리가 작성되는 본 폴더 통째로 삭제 + 사용처 4 군데 교체.
``grep -r "STUB:" controller/gogoping-controller/`` 로 한 번에 찾을 수 있다.
"""
from __future__ import annotations

from ._base import StubInfiniteRunning, StubRunningThenSuccess
from .stub_carry import StubCarry
from .stub_follow import StubFollow
from .stub_hideseek import StubHideseek

__all__ = [
    "StubCarry",
    "StubFollow",
    "StubHideseek",
    "StubRunningThenSuccess",
    "StubInfiniteRunning",
]
