"""# STUB: replace Day 3~4 — 공통 베이스 (N tick RUNNING 후 SUCCESS).

본 모듈은 *Day 1 walking skeleton* 단계의 placeholder behaviour 베이스 클래스다.
진짜 BT_*_sub 트리가 작성되는 Day 3~4 에 ``_stubs/`` 폴더 통째로 삭제 +
사용처 (BT_assist_main, BT_play_main 의 TaskSelector 자식) 교체된다.

## 본 폴더가 존재하는 이유 — walking skeleton

end-to-end 흐름 검증을 *진짜 task 구현 전에* 끝낸다. 즉::

    robot-web 버튼 → REST /api/mode → ROS srv SetGoal → command_listener →
    blackboard 세팅 + fsm.trigger → main.py 의 on_state_change →
    BT swap → MainTree (TaskSelector) tick → 자식 SUCCESS →
    main.py 의 _on_tree_success → assist_done/play_done trigger → IDLE 복귀

위 사슬의 *결선 자체* 가 동작하는지 보려면 TaskSelector 의 자식이 진짜
NavigateToPose / FaceTracking / ... 일 필요는 없다. "RUNNING 잠시 → SUCCESS"
정도면 충분 — 그래서 stub.

## 왜 ``DEFAULT_RUNNING_TICKS = 3`` 인가

너무 빨리 (1 tick 만에) SUCCESS 면 BT swap 이 즉시 일어나 admin UI 의 BT 상태 위젯에
"RUNNING 자식이 잠깐 보였다 사라지는" 시각 피드백이 안 보임. main.py 의 TICK_HZ=10 기준
~300ms 정도 보이는 게 디버깅·시연 모두에 적절.

## py_trees 의 auto-restart 와 ``initialise()``

py_trees 의 단독 ``tick_once()`` 는 직전 status 가 SUCCESS/FAILURE 면 다음 tick 에
``initialise()`` 를 자동 호출해 재시작한다. 본 클래스는 ``initialise()`` 에서 카운터를
리셋하므로 재진입 시 또 N tick 의 RUNNING 을 보여준다. Selector(memory=False) 등에서
같은 자식이 여러 번 re-tick 되어도 매번 N tick 보장.

## 교체 계획 (Day 3~4)

1. 진짜 ``bt/trees/sub_trees/BT_<name>_sub.py`` 작성 (build(ctx) 함수 export)
2. 사용처의 ``Stub<Name>`` import 를 ``build_<name>`` 호출로 교체
3. 본 폴더 ``_stubs/`` 통째로 삭제

## 청소 명령 (Day 5)

::

    grep -rn "STUB:" controller/gogoping-controller/

위 명령으로 본 폴더의 5개 파일 + 사용처 (BT_assist_main.py, BT_play_main.py) 의 import
라인이 모두 잡힘.
"""
from __future__ import annotations

import py_trees
from py_trees.common import Status


class StubRunningThenSuccess(py_trees.behaviour.Behaviour):
    """N tick 동안 RUNNING 리턴 후 SUCCESS. 본 클래스 자체는 인스턴스화하지 않고,
    각 task 별 서브클래스 (``StubCarry``, ``StubFollow``, ``StubLullaby``,
    ``StubHideseek``) 를 통해 사용 — 이름이 admin BT 위젯에 그대로 표시되도록.

    # STUB: replace Day 3~4 — 진짜 sub-tree (BT_carry_sub 등) 로 교체.
    """

    DEFAULT_RUNNING_TICKS = 3  # ~300ms @ 10Hz

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
