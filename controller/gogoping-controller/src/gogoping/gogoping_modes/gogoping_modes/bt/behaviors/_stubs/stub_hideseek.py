"""# STUB: replace Day 3~4 — BT_hide_and_seek_sub.py placeholder.

## 진짜 hide-and-seek sub tree 의 모양 (Day 3~4 작성 예정)

``BT_hide_and_seek_sub`` 는 숨바꼭질 task. 1회 실행 후 종료되는 가장 복잡한 sub tree —
``search_waypoints`` 리스트 길이에 따라 *동적 빌드* 되는 특이 케이스 (자세한
build 패턴: ``docs/conventions.md`` §4.1).

::

    Parallel(SuccessOnSelected=[HideSeekCore])
      ├─ ChildFaceTracker            # 매 tick 카메라 frame 에서 아이 얼굴 검색
      └─ Sequence: HideSeekCore (memory=True)
            ├─ NavigateToPose(hide_position_key)
            ├─ Sequence: Countdown30s
            │     ├─ UIPublish("카운트다운 시작")
            │     └─ Timer(duration=30.0)
            ├─ SearchPhase                       # waypoints 동적 build
            │     ├─ Sequence: Search_0 (NavTo + PanSweep + FoundChild? + Announce)
            │     ├─ Sequence: Search_1 (...)
            │     ├─ ...                          # N 개
            │     └─ UIPublish("못 찾았어요")
            └─ NavigateToPose(home_position_key)

blackboard read: ``HIDE_POSITION_KEY``, ``SEARCH_WAYPOINTS``, ``HOME_POSITION_KEY``,
                 ``TARGET_PERSON_ID``, ``FOUND``.
상세: ``docs/bt/trees/BT_hide_and_seek_sub.md`` + ``docs/conventions.md`` §4.1.

## 본 stub 의 동작

3 tick RUNNING → SUCCESS. 진짜 hide-and-seek 은 N waypoint 순회라 수십초~수분이지만
Day 1 단계엔 짧게.

## 교체 시점

Day 3~4. 다른 stub 과 달리 *동적 빌드* 패턴이라 ``build_hide_and_seek(ctx)`` 함수가
blackboard 의 ``SEARCH_WAYPOINTS`` 를 build 시점에 읽어 N 개 Sequence 를 생성. 자세한
구조는 ``conventions.md §4.1`` 참조 — 일반 build_*(ctx) 패턴과 다른 점만 거기 정리됨.
"""
from __future__ import annotations

from ._base import StubRunningThenSuccess


class StubHideseek(StubRunningThenSuccess):
    """hideseek sub tree 자리를 채우는 placeholder.

    # STUB: replace Day 3~4 —
    # bt/trees/sub_trees/BT_hide_and_seek_sub.py 의 build_hide_and_seek 로 교체.
    """

    def __init__(self, running_ticks: int | None = None):
        super().__init__(name="StubHideseek", running_ticks=running_ticks)
