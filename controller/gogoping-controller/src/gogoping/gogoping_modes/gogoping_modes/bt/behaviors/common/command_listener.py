"""CommandListener — UI 의 SetGoal / ForceState / SetRobotPose 서비스 요청을 받아 처리.

## 책임

1. ``gogoping_msgs/srv/SetGoal`` 서비스 서버 — 정상 mode 클릭 (UI 의 robot-web 메뉴).
   ``goal_reconciler.reconcile()`` 호출해 적절한 FSM trigger 발화.
2. ``gogoping_msgs/srv/ForceState`` 서비스 서버 — 디버그 강제 state 전이 (admin UI 의
   debug_state_bar). ``fsm.force_state(target)`` 직접 호출 — transition 규칙 우회.
3. ``gogoping_msgs/srv/SetRobotPose`` 서비스 서버 — 디버그 좌표 강제 override (admin UI 의
   MapStatusCard 디버그 입력). blackboard.ROBOT_POSE 강제 설정 + POSE_OVERRIDE_ACTIVE
   flag → PoseSubscriber 가 amcl_pose 메시지 W skip → 좌표 유지. clear=True 면 flag 해제.

## py_trees behavior 측면

본 behaviour 는 *모든 MainTree 의 monitor 분기에서 항상 tick* 된다 (10 state 의 root
Parallel 자식, ERROR/LOW_BATTERY_RETURNING lockdown 제외). 매 tick ``RUNNING`` 유지 —
SUCCESS / FAILURE 리턴 금지 (monitor 컨벤션, ``docs/conventions.md`` §2).

실제 trigger 발화는 ``update()`` 가 아닌 *서비스 콜백* 에서 (rclpy executor 가 별도 thread
또는 같은 thread 에서 호출). ``update()`` 자체는 빈 routine.

## ROS 의존성

``gogoping_msgs.srv.SetGoal`` 은 ``colcon build --packages-select gogoping_msgs`` 이후
생성되는 Python 바인딩. 본 모듈 import 는 conda env 만으로는 실패 — ROS 워크스페이스
sourcing 후 ROS 노드로 실행해야 동작.

(reconciler 로직 자체는 ``goal_reconciler.py`` 에 분리되어 있어 ROS 없이도 단위 테스트
가능 — 17 시나리오 검증 완료.)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Access, Status

from ....utils.goal_reconciler import reconcile

if TYPE_CHECKING:
    from ....context import Context


class CommandListener(py_trees.behaviour.Behaviour):
    """SetGoal.srv 서버 + 모든 MainTree 에 들어가는 monitor.

    - ``initialise()``: 서비스 서버 생성 (한 번만 — re-entry 시 재생성 안 함).
    - ``update()``: 매 tick ``RUNNING`` 리턴 (monitor 컨벤션).
    - ``terminate()``: ``new_status`` 무관 — 서비스 서버는 노드 라이프타임 동안 유지
      (트리 swap 마다 서비스 destroy/create 비용 회피).

    blackboard 권한은 ``goal_reconciler`` 가 받는 mock 호환 wrapper 를 거쳐 등록.
    """

    SERVICE_NAME = "set_goal"           # 상대 path — node namespace 가 /gogoping 으로 prefix
    FORCE_STATE_SERVICE_NAME = "debug/force_state"
    SET_ROBOT_POSE_SERVICE_NAME = "debug/set_robot_pose"
    EMERGENCY_STOP_SERVICE_NAME = "emergency_stop"   # /gogoping/emergency_stop (Trigger)

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context
        self._srv = None
        self._force_state_srv = None
        self._set_pose_srv = None
        self._estop_srv = None
        self._bb_writer: _BlackboardWriter | None = None
        self._pose_bb: py_trees.blackboard.Client | None = None

    def setup(self, **kwargs) -> None:
        """py_trees 가 트리 setup 시 1회 호출 — 서비스 서버 + blackboard 권한 등록."""
        # lazy import — ROS sourcing 안 된 환경에서도 본 모듈 import 가능하게
        from gogoping_msgs.srv import ForceState, SetGoal, SetRobotPose
        from std_srvs.srv import Trigger

        self._srv = self.ctx.node.create_service(
            SetGoal, self.SERVICE_NAME, self._on_set_goal_request,
        )
        self._force_state_srv = self.ctx.node.create_service(
            ForceState, self.FORCE_STATE_SERVICE_NAME, self._on_force_state_request,
        )
        self._set_pose_srv = self.ctx.node.create_service(
            SetRobotPose, self.SET_ROBOT_POSE_SERVICE_NAME, self._on_set_robot_pose_request,
        )
        self._estop_srv = self.ctx.node.create_service(
            Trigger, self.EMERGENCY_STOP_SERVICE_NAME, self._on_emergency_stop_request,
        )

        # blackboard writer — reconciler 에 주입할 wrapper.
        # 모든 cmd 관련 key 에 WRITE 권한 등록.
        self._bb_writer = _BlackboardWriter(self.name)

        # ROBOT_POSE / POSE_OVERRIDE_ACTIVE 직접 쓰기용 별도 client
        from ...blackboard import Keys as _Keys
        self._pose_bb = py_trees.blackboard.Client(name=f"{self.name}/pose_writer")
        self._pose_bb.register_key(key=_Keys.ROBOT_POSE, access=Access.WRITE)
        self._pose_bb.register_key(key=_Keys.POSE_OVERRIDE_ACTIVE, access=Access.WRITE)

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
        # Goal.msg → dict 변환 (평탄화: target_state 단일 필드)
        g = request.goal
        goal_dict = {
            "target_state": g.target_state,
            "destination_key": g.destination_key,
            "target_id": g.target_id,
            "search_waypoints": list(g.search_waypoints),
            "play_area_key": g.play_area_key,
        }

        # debug event (admin UI 추적용)
        dbg = getattr(self.ctx, "debug_events", None)
        if dbg is not None:
            dbg.event(
                "SetGoal",
                f"target_state={g.target_state!r}"
                f" dest={g.destination_key!r} target_id={g.target_id!r}"
                f" play_area={g.play_area_key!r}",
            )

        # reconcile — 순수 함수, 단위 테스트 17건 통과한 로직
        result = reconcile(goal_dict, self.ctx.fsm, self._bb_writer)

        if dbg is not None:
            dbg.event(
                "reconcile",
                f"trigger={result.trigger_fired!r} accepted={result.accepted}"
                f" reason={result.reason!r}",
                level="info" if result.accepted else "warn",
            )

        # 응답 채움
        response.accepted = result.accepted
        response.reason = result.reason

        # 로깅 — debug 시 도움
        self.ctx.node.get_logger().info(
            f"SetGoal target_state={g.target_state!r} → "
            f"accepted={result.accepted} trigger={result.trigger_fired!r} "
            f"reason={result.reason!r}"
        )

        return response

    # ------------------------------------------------------------ ForceState callback

    def _on_force_state_request(self, request, response):
        """``ForceState.srv`` 콜백 — admin UI DebugStatePanel 이 호출.

        transition 규칙 우회. ``fsm.force_state(target)`` 직접 호출 — CHARGING /
        LOW_BATTERY_RETURNING / ERROR 도 진입 가능.

        평탄화 (2026-05-25): sub_task 필드 제거. state 자체가 task 라 추가 분기 불필요.
        task body 의 destination_key / target_id 등을 디버그로 주고 싶으면 SetGoal.srv 사용.
        """
        target = request.target_state
        ok = self.ctx.fsm.force_state(target)
        response.accepted = ok
        response.reason = "" if ok else "invalid_state"
        self.ctx.node.get_logger().info(
            f"ForceState target={target!r} → accepted={ok}, "
            f"current_state={self.ctx.fsm.current_state!r}"
        )
        return response

    # ------------------------------------------------------------ Emergency stop callback

    def _on_emergency_stop_request(self, request, response):
        """``std_srvs/Trigger`` 콜백 — 긴급정지.

        Admin UI 의 e-stop 버튼 / 외부 안전 시스템이 호출. FSM 을 ERROR (terminal) 로
        강제 전이 → BT_error_main 빌드 → StopAllMotors 가 cmd_vel=0 + torque OFF 실행.

        ERROR 는 terminal — 사용자가 robot 재시작해야 복구 가능.
        idempotent — 이미 ERROR 인 상태에서 또 호출돼도 무해 (force_state 가 no-op).
        """
        from ...blackboard import Keys as _Keys

        # blackboard 에 사유 기록 — admin UI / DB log 가 활용
        self._bb_writer.set(_Keys.ERROR_REASON, "user_emergency_stop")
        self._bb_writer.set(_Keys.ERROR_SOURCE, "emergency_stop_service")

        ok = self.ctx.fsm.force_state("ERROR")
        response.success = bool(ok)
        response.message = "ERROR state entered" if ok else "force_state failed"
        self.ctx.node.get_logger().warning(
            f"EmergencyStop invoked → accepted={ok}, "
            f"current_state={self.ctx.fsm.current_state!r}"
        )
        return response

    # ------------------------------------------------------------ SetRobotPose callback

    def _on_set_robot_pose_request(self, request, response):
        """``SetRobotPose.srv`` 콜백 — admin UI MapStatusCard 디버그.

        - clear=True: POSE_OVERRIDE_ACTIVE 해제 → 다음 odom 메시지부터 live 복원.
        - clear=False: ROBOT_POSE = {x, y, yaw} 직접 W + POSE_OVERRIDE_ACTIVE=True
          → PoseSubscriber 가 다음 amcl_pose 메시지부터 W skip → 좌표 유지.
        """
        from ...blackboard import Keys as _Keys

        if request.clear:
            self._pose_bb.set(_Keys.POSE_OVERRIDE_ACTIVE, False)
            self.ctx.node.get_logger().info(
                "SetRobotPose: override cleared — live odom 복원"
            )
        else:
            self._pose_bb.set(
                _Keys.ROBOT_POSE,
                {"x": float(request.x), "y": float(request.y), "yaw": float(request.yaw)},
            )
            self._pose_bb.set(_Keys.POSE_OVERRIDE_ACTIVE, True)
            self.ctx.node.get_logger().info(
                f"SetRobotPose: override active — "
                f"x={request.x:.2f}, y={request.y:.2f}, yaw={request.yaw:.2f}"
            )

        response.accepted = True
        response.reason = ""
        return response


# ---------------------------------------------------------------- Blackboard wrapper


class _BlackboardWriter:
    """py_trees Blackboard Client 를 reconciler 의 ``set(key, value)`` 시그니처에 맞춤.

    모든 cmd 관련 key 에 WRITE 권한 미리 등록 — register 누락 시 reconciler 가 KeyError
    터지는 거 방지.
    """

    _WRITE_KEYS = (
        "destination_key", "target_person_id",
        "search_waypoints",
        # _on_emergency_stop_request 가 fault reason 기록용으로 W
        "error_reason", "error_source",
        # HIDEANDSEEK 진입 시 reconciler 가 set (Task 8) — play_area + reset 3 키
        "hideseek_play_area_key", "hideseek_registered_ids",
        "hideseek_caught_ids", "hideseek_phase",
    )

    def __init__(self, behaviour_name: str):
        self._client = py_trees.blackboard.Client(name=f"{behaviour_name}/writer")
        for key in self._WRITE_KEYS:
            self._client.register_key(key=key, access=Access.WRITE)

    def set(self, key: str, value) -> None:
        self._client.set(key, value)
