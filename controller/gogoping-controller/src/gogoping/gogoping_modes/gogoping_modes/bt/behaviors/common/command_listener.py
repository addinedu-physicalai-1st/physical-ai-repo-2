"""CommandListener — UI 의 SetGoal.srv 요청을 받아 reconciler 호출.

## 책임

1. ``gogoping_msgs/srv/SetGoal`` 서비스 서버 1개 생성 (상대 path ``"set_goal"`` —
   node namespace ``"gogoping"`` 이 prefix → 실제 ``/gogoping/set_goal``).
2. 서비스 콜백에서 ``goal_reconciler.reconcile()`` 호출.
3. reconcile 결과를 ``SetGoal.Response`` 로 변환해 클라이언트에 응답.

## py_trees behavior 측면

본 behaviour 는 *모든 MainTree 의 monitor 분기에서 항상 tick* 된다 (idle/assist/play/
manual/charging/error 의 root Parallel 자식). 매 tick ``RUNNING`` 유지 — SUCCESS / FAILURE
리턴 금지 (monitor 컨벤션, ``docs/conventions.md`` §2).

실제 trigger 발화는 ``update()`` 가 아닌 *서비스 콜백* 에서 (rclpy executor 가 별도 thread
또는 같은 thread 에서 호출). ``update()`` 자체는 빈 routine.

## ROS 의존성

``gogoping_msgs.srv.SetGoal`` 은 ``colcon build --packages-select gogoping_msgs`` 이후
생성되는 Python 바인딩. 본 모듈 import 는 conda env 만으로는 실패 — ROS 워크스페이스
sourcing 후 ROS 노드로 실행해야 동작.

(reconciler 로직 자체는 ``goal_reconciler.py`` 에 분리되어 있어 ROS 없이도 단위 테스트
가능 — 13 시나리오 검증 완료.)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Access, Status

from .goal_reconciler import reconcile

if TYPE_CHECKING:
    from ...context import Context


class CommandListener(py_trees.behaviour.Behaviour):
    """SetGoal.srv 서버 + 모든 MainTree 에 들어가는 monitor.

    - ``initialise()``: 서비스 서버 생성 (한 번만 — re-entry 시 재생성 안 함).
    - ``update()``: 매 tick ``RUNNING`` 리턴 (monitor 컨벤션).
    - ``terminate()``: ``new_status`` 무관 — 서비스 서버는 노드 라이프타임 동안 유지
      (트리 swap 마다 서비스 destroy/create 비용 회피).

    blackboard 권한은 ``goal_reconciler`` 가 받는 mock 호환 wrapper 를 거쳐 등록.
    """

    SERVICE_NAME = "set_goal"  # 상대 path — node namespace 가 /gogoping 으로 prefix

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context
        self._srv = None
        self._bb_writer: _BlackboardWriter | None = None

    def setup(self, **kwargs) -> None:
        """py_trees 가 트리 setup 시 1회 호출 — 서비스 서버 + blackboard 권한 등록."""
        # lazy import — ROS sourcing 안 된 환경에서도 본 모듈 import 가능하게
        from gogoping_msgs.srv import SetGoal

        self._srv_type = SetGoal
        self._srv = self.ctx.node.create_service(
            SetGoal, self.SERVICE_NAME, self._on_set_goal_request,
        )

        # blackboard writer — reconciler 에 주입할 wrapper.
        # 모든 cmd 관련 key 에 WRITE 권한 등록.
        self._bb_writer = _BlackboardWriter(self.name)

    def update(self) -> Status:
        # monitor 컨벤션 — 항상 RUNNING, 부수효과는 서비스 콜백에서.
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        # 서비스 서버는 노드 라이프타임 동안 유지 — 트리 swap 마다 destroy 안 함.
        # (필요해지면 self._srv.destroy() 추가)
        pass

    # ------------------------------------------------------------ Service callback

    def _on_set_goal_request(self, request, response):
        """``SetGoal.srv`` 콜백 — request.goal 을 reconciler 에 전달.

        rclpy 가 별도 thread 또는 spin loop 에서 호출. fsm.trigger() 가 _on_state_change
        콜백을 동기 호출하므로 main.py 의 ``_on_state_change`` 가 같은 thread 에서
        실행될 수 있음. 트리 swap 은 main.py 가 다음 tick 에 처리 (deferred).
        """
        # Goal.msg → dict 변환
        g = request.goal
        goal_dict = {
            "mode": g.mode,
            "task": g.task,
            "carry_mode": g.carry_mode,
            "destination_key": g.destination_key,
            "target_id": g.target_id,
        }

        # reconcile — 순수 함수, 단위 테스트 13건 통과한 로직
        result = reconcile(goal_dict, self.ctx.fsm, self._bb_writer)

        # 응답 채움
        response.accepted = result.accepted
        response.reason = result.reason

        # 로깅 — debug 시 도움
        self.ctx.node.get_logger().info(
            f"SetGoal mode={g.mode!r} task={g.task!r} → "
            f"accepted={result.accepted} trigger={result.trigger_fired!r} "
            f"reason={result.reason!r}"
        )

        return response


# ---------------------------------------------------------------- Blackboard wrapper


class _BlackboardWriter:
    """py_trees Blackboard Client 를 reconciler 의 ``set(key, value)`` 시그니처에 맞춤.

    모든 cmd 관련 key 에 WRITE 권한 미리 등록 — register 누락 시 reconciler 가 KeyError
    터지는 거 방지.
    """

    _WRITE_KEYS = (
        "assist_task", "play_task", "carry_mode",
        "destination_key", "target_person_id",
    )

    def __init__(self, behaviour_name: str):
        self._client = py_trees.blackboard.Client(name=f"{behaviour_name}/writer")
        for key in self._WRITE_KEYS:
            self._client.register_key(key=key, access=Access.WRITE)

    def set(self, key: str, value) -> None:
        self._client.set(key, value)
