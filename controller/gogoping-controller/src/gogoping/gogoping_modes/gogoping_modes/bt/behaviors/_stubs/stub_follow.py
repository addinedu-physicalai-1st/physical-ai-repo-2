"""# STUB: replace Day 3~4 — BT_follow_sub.py placeholder.

## 진짜 follow sub tree 의 모양 (Day 3~4 작성 예정)

``BT_follow_sub`` 는 추종 task 의 root. 정상 모드와 Loss Recovery 의 2-phase 구조:

::

    Selector(name="FollowCore", memory=False)
      ├─ Sequence: IsTargetVisible → MaintainDistance →
      │            (FaceTracking | RaiseCameraPan)   # 카메라 자동 추적
      │
      └─ Sequence: LossRecovery
            ├─ StopBase
            ├─ PanCameraSweep                       # 좌우 stop 자세 sweep
            ├─ WaitForReappear (timeout)
            └─ (대상 재발견 시 정상 모드 자동 복귀)

blackboard read: ``TARGET_VISIBLE``, ``TARGET_POSE``, ``TARGET_FACE_BBOX``,
                 ``TARGET_SEEN_AT``, ``TARGET_PERSON_ID``.
상세: ``docs/bt/trees/BT_follow_sub.md`` (스켈레톤 명세).

## 본 stub 의 동작

기본 3 tick RUNNING → SUCCESS. 진짜 follow 는 *사람이 사라지지 않는 한* 계속 RUNNING
이어야 하지만 (사실상 timeout 없는 task), Day 1 walking skeleton 단계엔 SUCCESS 로
끝내서 IDLE 복귀 사이클 검증.

## 교체 시점

Day 3~4. 사용처: BT_assist_main 의 TaskSelector ASSIST/follow 자식.
carry+follow 모드는 ``StubCarry`` 가 ``StubFollow`` 를 재호출하는 구조였지만,
진짜 ``BT_carry_sub`` 가 ``BT_follow_sub`` 를 합성하면서 자연 해결됨.
"""
from __future__ import annotations

from ._base import StubRunningThenSuccess


class StubFollow(StubRunningThenSuccess):
    """follow sub tree 자리를 채우는 placeholder.

    # STUB: replace Day 3~4 — bt/trees/sub_trees/BT_follow_sub.py 의 build_follow 로 교체.
    """

    def __init__(self, running_ticks: int | None = None):
        super().__init__(name="StubFollow", running_ticks=running_ticks)
