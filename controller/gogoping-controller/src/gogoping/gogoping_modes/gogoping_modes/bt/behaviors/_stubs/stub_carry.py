"""# STUB: replace Day 3~4 — BT_carry_sub.py placeholder.

## 진짜 carry sub tree 의 모양 (Day 3~4 작성 예정)

``BT_carry_sub`` 는 운반 task 의 root. ``blackboard.CARRY_MODE`` 값에 따라 3-way 분기:

::

    Selector(name="CarryCore", memory=False)
      ├─ Sequence: CheckCarryMode("manual") → EnableManualControl → WaitForExit
      ├─ Sequence: CheckCarryMode("goto")   → LoadStabilityCheck →
      │                                       NavigateToPose(destination_key) →
      │                                       UIPublish("도착했어요")
      └─ Sequence: CheckCarryMode("follow") → FollowSubTree
                                             # carry+follow = 짐 들고 사람 따라가기

상세: ``docs/bt/trees/BT_carry_sub.md`` (스켈레톤 명세).

## 본 stub 의 동작

기본 3 tick (~300ms @ 10Hz) RUNNING → SUCCESS. main.py 가 root SUCCESS 를 ASSIST 완료로
해석 → ``assist_done`` trigger 발화 → IDLE 복귀. carry_mode 분기는 시뮬레이션 안 함.

## 교체 시점

Day 3~4. 작성 순서:
1. ``bt/trees/sub_trees/BT_carry_sub.py`` 의 ``build(ctx)`` 함수 작성
2. ``bt/trees/main_trees/BT_assist_main.py`` 의 ``StubCarry()`` 호출을
   ``build_carry(ctx)`` 로 교체
3. 모든 stub 교체 완료 후 ``_stubs/`` 폴더 삭제

자세한 stub 사용 컨벤션: ``_base.py`` 의 module docstring.
"""
from __future__ import annotations

from ._base import StubRunningThenSuccess


class StubCarry(StubRunningThenSuccess):
    """carry sub tree 자리를 채우는 placeholder.

    이름 ``"StubCarry"`` 가 admin BT 상태 위젯의 sub 칸 children 에 표시됨 —
    실제 작동 시 ``"BT_carry_sub"`` 아래에 ``"LoadStabilityCheck"`` /
    ``"NavigateToPose(destination_key)"`` 등이 나오게 될 자리.

    # STUB: replace Day 3~4 — bt/trees/sub_trees/BT_carry_sub.py 의 build_carry 로 교체.
    """

    def __init__(self, running_ticks: int | None = None):
        super().__init__(name="StubCarry", running_ticks=running_ticks)
