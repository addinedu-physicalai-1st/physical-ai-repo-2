"""# STUB — 공통 베이스 (2 종류).

진짜 BT_*_sub 트리가 작성될 때 ``_stubs/`` 폴더 통째로 삭제 + 사용처 (BT_assist_main /
BT_play_main 의 TaskSelector 자식) 교체.

## 2 가지 stub 행동 패턴

진짜 sub-tree 의 *의미* 와 일치하도록 두 가지 베이스를 구분:

- ``StubRunningThenSuccess`` — N tick RUNNING 후 SUCCESS.
  진짜 동작에 *유한 종료* 가 있는 task 용:
    * carry+goto: 목적지 도달 시 SUCCESS
    * hideseek: 1회 사이클 후 SUCCESS

- ``StubInfiniteRunning`` — 항상 RUNNING. terminate 까지 안 끝남.
  진짜 동작이 *외부 종료 신호 의존* 인 task 용:
    * follow: 사람 보이는 한 계속
    * lullaby: 사용자 stop 명령까지

## py_trees 의 auto-restart 와 ``initialise()``

py_trees 의 단독 ``tick_once()`` 는 직전 status 가 SUCCESS/FAILURE 면 다음 tick 에
``initialise()`` 를 자동 호출해 재시작한다. ``StubRunningThenSuccess`` 는
``initialise()`` 에서 카운터를 리셋 — Selector(memory=False) re-entry 안전.

## 교체 계획

1. 진짜 ``bt/trees/sub_trees/BT_<name>_sub.py`` 작성 (build(ctx) 함수 export)
2. 사용처의 ``Stub<Name>`` import 를 ``build_<name>`` 호출로 교체
3. 본 폴더 ``_stubs/`` 통째로 삭제

## 청소 명령

::

    grep -rn "STUB:" controller/gogoping-controller/

위 명령으로 본 폴더의 5개 파일 + 사용처 (BT_assist_main.py, BT_play_main.py) 의 import
라인이 모두 잡힘.
"""
from __future__ import annotations

import py_trees
from py_trees.common import Status


class StubRunningThenSuccess(py_trees.behaviour.Behaviour):
    """N tick 동안 RUNNING 리턴 후 SUCCESS.

    유한 종료 의미가 있는 task 의 stub (carry / hideseek).

    # STUB — 진짜 sub-tree 로 교체.
    """

    DEFAULT_RUNNING_TICKS = 30  # 3초 @ TICK_HZ=10 (관찰 가능 + 적당히 짧음)

    def __init__(self, name: str, running_ticks: int | None = None):
        super().__init__(name)
        self._target = running_ticks or self.DEFAULT_RUNNING_TICKS
        self._count = 0

    def initialise(self) -> None:
        """매 진입 시 카운터 리셋 — Selector(memory=False) re-entry 안전."""
        self._count = 0

    def update(self) -> Status:
        self._count += 1
        if self._count >= self._target:
            return Status.SUCCESS
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        """idempotent — stub 이라 cleanup 할 외부 자원 없음. 진짜 sub-tree 로
        교체 시 nav2 goal cancel / torque 복원 등 본 메서드에 추가."""
        self._count = 0


class StubInfiniteRunning(py_trees.behaviour.Behaviour):
    """항상 RUNNING 리턴 — 외부 종료 신호 (cancel / battery_low / fault) 만 종료.

    follow / lullaby 같이 *지속적 작업* 의 stub. 진짜 동작과 의미상 같음.

    # STUB — 진짜 sub-tree 로 교체.
    """

    def update(self) -> Status:
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        """idempotent — stub 이라 cleanup 할 외부 자원 없음. 진짜 sub-tree 로
        교체 시 vision/camera_pan 정지 등 본 메서드에 추가."""
        pass
