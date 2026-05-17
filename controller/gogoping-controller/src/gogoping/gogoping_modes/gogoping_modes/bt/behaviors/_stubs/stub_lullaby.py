"""# STUB: replace Day 3~4 — BT_lullaby_sub.py placeholder.

## 진짜 lullaby sub tree 의 모양 (Day 3~4 작성 예정)

``BT_lullaby_sub`` 는 자장가 task. 매우 단순 — UI 가 mp3 재생, BT 는 종료 신호만 기다림:

::

    Sequence(name="LullabyCore", memory=True)
      ├─ UIPublish("자장가 시작")        # robot-web 에 mp3 재생 명령
      ├─ WaitForStopCommand              # blackboard 의 cancel 플래그 폴링
      └─ UIPublish("자장가 종료")

ASSIST 분류 (교사 명령) — 아이 자발적 놀이 (PLAY 의 hideseek) 와 구분.
상세: ``docs/bt/trees/BT_lullaby_sub.md``.

## 본 stub 의 동작

3 tick RUNNING → SUCCESS. 진짜 lullaby 는 *사용자가 정지 명령* 줄 때까지 RUNNING
이지만, Day 1 단계엔 timer 처럼 종료.

## 교체 시점

Day 3~4. 진짜 트리는 ``WaitForStopCommand`` behavior (blackboard cancel 플래그 폴링)
구현이 핵심. ``UIPublish`` 는 범용 behavior (이미 spec 만 있음).
"""
from __future__ import annotations

from ._base import StubRunningThenSuccess


class StubLullaby(StubRunningThenSuccess):
    """lullaby sub tree 자리를 채우는 placeholder.

    # STUB: replace Day 3~4 — bt/trees/sub_trees/BT_lullaby_sub.py 의 build_lullaby 로 교체.
    """

    def __init__(self, running_ticks: int | None = None):
        super().__init__(name="StubLullaby", running_ticks=running_ticks)
