"""ROS 2 bridge for GogoPing FSM/BT.

SetGoal.srv client + ``/gogoping/state`` topic subscriber. teleop / noriarm / eduping
ros_bridge.py 와 같은 패턴 — 별도 daemon thread 에서 rclpy spin, 모든 공유 상태 lock 보호.

asyncio (FastAPI) 핸들러는 본 모듈의 동기 메서드 (``send_goal_sync``, ``get_latest_state``,
``register_state_callback``) 만 호출 — rclpy API 직접 호출 금지.

ROS 환경 미source 시 ``ros_available() == False`` 반환 — 호출자가 503 응답 처리.
"""
from __future__ import annotations

import collections
import json
import logging
import math
import os
import threading
import time
from typing import Any, Callable

from .state_to_goal import Goal

logger = logging.getLogger(__name__)


# 토픽 / 서비스 이름 (gogoping_modes 와 일치 — 모두 /gogoping/* namespace)
TOPIC_STATE = "/gogoping/state"
TOPIC_NAV_DEBUG_EVENTS = "/gogoping/debug/nav_events"
# UIPublisher 의 일회성 이벤트 (lullaby_play / announce / countdown_start ...).
# robot-web 만 구독하던 토픽 — admin NavDebugLogCard 가 cancel chain 옆에서
# UX 이벤트 흐름을 cross-correlate 할 수 있도록 control-service 가 같이 구독해서
# nav_event 파이프라인에 source="UI" 로 인젝션한다.
TOPIC_UI_EVENT = "/gogoping/ui_event"
# 카메라 pan 서보 setpoint — gogoping_camera_pan/camera_pan_client.TOPIC_CMD_PAN 와 동일.
# PanCameraSweep (BT) / admin UI 슬라이더 / keyboard_teleop 가 publish. 빈도 저 —
# step 진입 시 1회만 publish (servo_bridge 의 20Hz 재송신은 별도 시리얼 채널).
TOPIC_CAMERA_PAN_CMD = "/servo_bridge/cmd_pan"
SERVICE_SET_GOAL = "/gogoping/set_goal"
SERVICE_FORCE_STATE = "/gogoping/debug/force_state"
SERVICE_SET_BATTERY_LEVEL = "/gogoping/sim/set_battery_level"
SERVICE_SET_ROBOT_POSE = "/gogoping/debug/set_robot_pose"
SERVICE_SET_GAZEBO_POSE = "/gogoping/sim/teleport_pose"
SERVICE_EMERGENCY_STOP = "/gogoping/emergency_stop"
SERVICE_SET_BLACKBOARD = "/gogoping/blackboard/set"
# gogoping_modes 노드 (namespace gogoping, name gogoping_modes) 의 표준 ParamServer.
# admin UI 에서 IDLE → RETURNING 임계값 (idle_timeout_seconds) 조정 시 호출.
SERVICE_SET_PARAMETERS = "/gogoping/gogoping_modes/set_parameters"
TOPIC_FOLLOW_TARGET = "/gogoping/follow_target"
TOPIC_FOLLOW_HINT = "/gogoping/follow_hint"
TOPIC_TRACKING_STATE = "/gogoping/tracking_state"

# Blackboard 키 — gogoping_modes 의 SetBlackboard 서버가 허용하는 allowlist 와 일치.
BB_KEY_HIDESEEK_REGISTERED_IDS = "hideseek_registered_ids"
BB_KEY_HIDESEEK_CAUGHT_IDS = "hideseek_caught_ids"
BB_KEY_HIDESEEK_SKIP_COUNTDOWN = "hideseek_skip_countdown"
BB_KEY_HIDESEEK_PATROL_ONLY = "hideseek_patrol_only"

# admin UI NavDebugLogCard 가 WS 연결 시 backfill 받는 최근 이벤트 수.
# 시나리오 재현 직후 늦게 연결해도 직전 cancel chain 한 cycle 정도는 보임.
NAV_EVENT_BUFFER_SIZE = 200


def ros_available() -> bool:
    """rclpy + gogoping_msgs import 가능 여부.

    ROS sourcing 안 됐거나 gogoping_msgs 빌드 전이면 False.
    """
    try:
        import rclpy  # noqa: F401
        from gogoping_msgs.srv import (  # noqa: F401
            ForceState, SetBatteryLevel, SetBlackboard, SetGazeboPose,
            SetGoal, SetRobotPose,
        )
        return True
    except ImportError:
        return False


class BridgeUnavailable(RuntimeError):
    """초기화 단계에서 ROS 의존성 누락 / 서비스 server 부재 등."""


class GogopingRosBridge:
    """gogoping_modes 노드와의 ROS 다리.

    - ``send_goal_sync(goal)``: SetGoal.srv 동기 호출 (asyncio thread 에서 호출 OK)
    - ``get_latest_state()``: 최근 ``/gogoping/state`` 메시지 (없으면 None)
    - ``register_state_callback(fn)``: 새 state 메시지 도착 시 ``fn(dict)`` 호출.
      WebSocket fan-out 에 사용.
    """

    SEND_GOAL_TIMEOUT_S = 2.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest_state: dict | None = None
        self._state_callbacks: list[Callable[[dict], None]] = []
        self._nav_event_callbacks: list[Callable[[dict], None]] = []
        self._nav_event_buffer: collections.deque[dict] = collections.deque(
            maxlen=NAV_EVENT_BUFFER_SIZE,
        )
        self._ros_ok = False
        self._spin_thread: threading.Thread | None = None

        # rclpy 객체는 start() 에서만 생성 (테스트가 mock 으로 대체 가능)
        self._node: Any = None
        self._cli: Any = None              # SetGoal.srv client
        self._force_state_cli: Any = None  # ForceState.srv client (디버그 전용)
        self._set_battery_cli: Any = None  # SetBatteryLevel.srv client (sim 디버그 전용)
        self._set_robot_pose_cli: Any = None  # SetRobotPose.srv client (디버그 전용)
        self._set_gazebo_pose_cli: Any = None  # SetGazeboPose.srv client (sim 디버그 전용)
        self._estop_cli: Any = None        # std_srvs/Trigger client — emergency_stop
        self._set_params_cli: Any = None   # rcl_interfaces/SetParameters — idle_timeout 등 ROS param 조정
        self._set_blackboard_cli: Any = None  # SetBlackboard.srv client — hideseek registered_ids / caught_ids
        self._sub: Any = None              # /gogoping/state subscriber
        self._nav_event_sub: Any = None    # /gogoping/debug/nav_events subscriber
        self._nav_event_pub: Any = None    # /gogoping/debug/nav_events publisher (AdminUI 입력 송출)
        self._ui_event_sub: Any = None     # /gogoping/ui_event subscriber → nav_event 파이프라인에 source="UI" 로 인젝션
        self._camera_pan_sub: Any = None   # /servo_bridge/cmd_pan subscriber → source="CamPan"
        self._follow_target_pub: Any = None   # /gogoping/follow_target publisher
        self._follow_hint_pub: Any = None     # /gogoping/follow_hint publisher (debug)
        self._follow_state_sub: Any = None    # /gogoping/follow_state subscriber
        self._last_follow_state: str | None = None
        self._follow_state_callbacks: list[Callable[[str], None]] = []
        self._tracking_state_sub: Any = None  # /gogoping/tracking_state subscriber
        self._last_tracking_state: dict | None = None
        self._tracking_state_callbacks: list[Callable[[dict], None]] = []
        self._executor: Any = None

        # 숨바꼭질 caught_ids 누적 캐시 — append semantics 구현용.
        # SetBlackboard.srv 는 set 만 지원하므로, control-service 가 round 별 누적 set 을
        # 유지하고 매 caught 마다 sorted list 전체를 셋팅한다. recruit-complete 호출 시 reset.
        # 단일 control-service 프로세스 가정 — multi-replica 운영은 추후 BT 측 append 서비스
        # 분리 시 검토.
        self._hideseek_caught_lock = threading.Lock()
        self._hideseek_caught_ids_cache: set[int] = set()

    # ----------------------------------------------------------- lifecycle

    def start(self) -> None:
        """rclpy 노드 생성 + spin thread 시작.

        ROS sourcing 안 됐으면 ``BridgeUnavailable`` 발생.
        """
        if not ros_available():
            raise BridgeUnavailable(
                "rclpy 또는 gogoping_msgs import 실패 — ROS source / colcon build 후 재시작"
            )

        # lazy import (top-level 에서 import 하면 ROS 없는 환경에서 control-service 자체가 죽음)
        import rclpy
        from gogoping_msgs.srv import (
            ForceState, SetBatteryLevel, SetBlackboard, SetGazeboPose,
            SetGoal, SetRobotPose,
        )
        from rcl_interfaces.srv import SetParameters
        from std_msgs.msg import String
        from std_srvs.srv import Trigger

        if "ROS_DOMAIN_ID" not in os.environ:
            raise BridgeUnavailable(
                "ROS_DOMAIN_ID 환경변수 미설정 — 201~219 중 할당된 ID 사용"
            )

        # rclpy 가 이미 초기화되어 있을 수 있음 (다른 bridge 가 먼저 init).
        if not rclpy.ok():
            rclpy.init()

        self._node = rclpy.create_node("gogoping_control_bridge")
        self._cli = self._node.create_client(SetGoal, SERVICE_SET_GOAL)
        self._force_state_cli = self._node.create_client(ForceState, SERVICE_FORCE_STATE)
        self._set_battery_cli = self._node.create_client(
            SetBatteryLevel, SERVICE_SET_BATTERY_LEVEL,
        )
        self._set_robot_pose_cli = self._node.create_client(
            SetRobotPose, SERVICE_SET_ROBOT_POSE,
        )
        self._set_gazebo_pose_cli = self._node.create_client(
            SetGazeboPose, SERVICE_SET_GAZEBO_POSE,
        )
        self._estop_cli = self._node.create_client(
            Trigger, SERVICE_EMERGENCY_STOP,
        )
        self._set_params_cli = self._node.create_client(
            SetParameters, SERVICE_SET_PARAMETERS,
        )
        self._set_blackboard_cli = self._node.create_client(
            SetBlackboard, SERVICE_SET_BLACKBOARD,
        )
        self._sub = self._node.create_subscription(
            String, TOPIC_STATE, self._on_state_msg, 10,
        )
        # nav cancel chain debug — admin UI NavDebugLogCard 가 WS 로 받음. depth=20
        # publisher 와 맞춰 burst 안 잃도록.
        self._nav_event_sub = self._node.create_subscription(
            String, TOPIC_NAV_DEBUG_EVENTS, self._on_nav_event_msg, 20,
        )
        # admin UI 가 누른 버튼 → 같은 토픽에 source="AdminUI" 로 publish. 자기 subscription
        # 으로 loopback 받아 ring buffer + WS 합류 (controller 측 publisher 들과 동일 경로).
        self._nav_event_pub = self._node.create_publisher(
            String, TOPIC_NAV_DEBUG_EVENTS, 20,
        )
        # /gogoping/ui_event 도 같이 구독 — UIPublisher 의 일회성 이벤트 (lullaby_play 등)
        # 를 source="UI" 로 nav_event 파이프라인에 인젝션 (publish 아닌 직접 callback 호출).
        self._ui_event_sub = self._node.create_subscription(
            String, TOPIC_UI_EVENT, self._on_ui_event_msg, 10,
        )
        # /servo_bridge/cmd_pan (Float32 deg) 도 구독 — 카메라 pan 명령 흐름을
        # source="CamPan" 으로 nav_event 파이프라인에 인젝션.
        from std_msgs.msg import Float32
        self._camera_pan_sub = self._node.create_subscription(
            Float32, TOPIC_CAMERA_PAN_CMD, self._on_camera_pan_msg, 10,
        )
        # follow target publisher + tracking state subscriber
        from gogoping_msgs.msg import FollowTarget, TrackingState
        self._follow_target_pub = self._node.create_publisher(
            FollowTarget, TOPIC_FOLLOW_TARGET, 10,
        )
        # follow_hint publisher (debug 패널용 — WAITING_HINT 모드에 left/right/front/back 발행)
        self._follow_hint_pub = self._node.create_publisher(
            String, TOPIC_FOLLOW_HINT, 10,
        )
        # follow_state subscriber — follow_node 가 mode 전이 시 publish
        self._follow_state_sub = self._node.create_subscription(
            String, "/gogoping/follow_state", self._on_follow_state, 10,
        )
        self._tracking_state_sub = self._node.create_subscription(
            TrackingState, TOPIC_TRACKING_STATE, self._on_tracking_state, 10,
        )
        self._executor = rclpy.executors.SingleThreadedExecutor()
        self._executor.add_node(self._node)

        self._ros_ok = True
        self._spin_thread = threading.Thread(
            target=self._spin, name="gogoping_bridge_spin", daemon=True,
        )
        self._spin_thread.start()
        logger.info("GogopingRosBridge started")

    def shutdown(self) -> None:
        if not self._ros_ok:
            return
        self._ros_ok = False
        if self._executor is not None:
            self._executor.shutdown()
        if self._node is not None:
            self._node.destroy_node()
        if self._spin_thread is not None and self._spin_thread.is_alive():
            self._spin_thread.join(timeout=1.0)
        logger.info("GogopingRosBridge stopped")

    def _spin(self) -> None:
        try:
            while self._ros_ok:
                self._executor.spin_once(timeout_sec=0.1)
        except Exception as e:
            logger.exception(f"GogopingRosBridge spin 오류: {e}")

    # ----------------------------------------------------------- send_goal

    def send_goal_sync(self, goal: Goal) -> tuple[bool, str]:
        """SetGoal.srv 동기 호출. ``(accepted, reason)`` 반환.

        ``SEND_GOAL_TIMEOUT_S`` 초 내 응답 없으면 ``(False, "timeout")``.
        서비스 미가용 시 ``(False, "service_unavailable")``.
        """
        if not self._ros_ok or self._cli is None:
            return False, "bridge_not_started"

        # gogoping_modes 가 살아있는지 — service 가능 여부 빠른 확인
        if not self._cli.service_is_ready():
            if not self._cli.wait_for_service(timeout_sec=0.5):
                return False, "service_unavailable"

        from gogoping_msgs.srv import SetGoal
        req = SetGoal.Request()
        req.goal.target_state = goal.target_state
        req.goal.destination_key = goal.destination_key
        req.goal.target_id = goal.target_id
        req.goal.search_waypoints = list(goal.search_waypoints)
        req.goal.play_area_key = goal.play_area_key

        future = self._cli.call_async(req)
        deadline = time.time() + self.SEND_GOAL_TIMEOUT_S
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False, "timeout"
        result = future.result()
        return bool(result.accepted), str(result.reason)

    # ----------------------------------------------------------- force_state (디버그)

    def force_state_sync(self, target_state: str) -> tuple[bool, str]:
        """**디버그 전용** — FSM 강제 state 전이.

        ``ForceState.srv`` 동기 호출. transition 규칙 우회 — CHARGING /
        LOW_BATTERY_RETURNING / ERROR 도 진입 가능.

        평탄화 (2026-05-25): sub_task 인자 제거. state 자체가 task 라 추가 분기 불필요.
        task body 의 destination_key / target_id 등을 디버그로 주려면 SetGoal.srv 사용.
        """
        if not self._ros_ok or self._force_state_cli is None:
            return False, "bridge_not_started"

        if not self._force_state_cli.service_is_ready():
            if not self._force_state_cli.wait_for_service(timeout_sec=0.5):
                return False, "service_unavailable"

        from gogoping_msgs.srv import ForceState
        req = ForceState.Request()
        req.target_state = target_state

        future = self._force_state_cli.call_async(req)
        deadline = time.time() + self.SEND_GOAL_TIMEOUT_S
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False, "timeout"
        result = future.result()
        return bool(result.accepted), str(result.reason)

    # ----------------------------------------------------------- set_battery (sim 디버그)

    def set_battery_level_sync(self, level: float) -> tuple[bool, str]:
        """**sim 디버그 전용** — sim_battery_node 의 배터리 레벨 강제 설정.

        ``gogoping_msgs/srv/SetBatteryLevel`` 동기 호출. 운영(실물 Pi) 환경엔 server
        없음 → ``(False, "service_unavailable")`` 반환.
        """
        if not self._ros_ok or self._set_battery_cli is None:
            return False, "bridge_not_started"

        if not self._set_battery_cli.service_is_ready():
            if not self._set_battery_cli.wait_for_service(timeout_sec=0.5):
                return False, "service_unavailable"

        from gogoping_msgs.srv import SetBatteryLevel
        req = SetBatteryLevel.Request()
        req.level = float(level)

        future = self._set_battery_cli.call_async(req)
        deadline = time.time() + self.SEND_GOAL_TIMEOUT_S
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False, "timeout"
        result = future.result()
        return bool(result.accepted), str(result.reason)

    # ----------------------------------------------------------- set_robot_pose (디버그)

    def set_robot_pose_sync(
        self, x: float, y: float, yaw: float, clear: bool = False,
    ) -> tuple[bool, str]:
        """**디버그 전용** — 로봇 좌표 강제 override.

        ``gogoping_msgs/srv/SetRobotPose`` 동기 호출. clear=True 면 override 해제 (live
        odom 복원). clear=False 면 (x, y, yaw) 로 blackboard.ROBOT_POSE 강제 + odom
        suppress flag 활성.
        """
        if not self._ros_ok or self._set_robot_pose_cli is None:
            return False, "bridge_not_started"

        if not self._set_robot_pose_cli.service_is_ready():
            if not self._set_robot_pose_cli.wait_for_service(timeout_sec=0.5):
                return False, "service_unavailable"

        from gogoping_msgs.srv import SetRobotPose
        req = SetRobotPose.Request()
        req.x = float(x)
        req.y = float(y)
        req.yaw = float(yaw)
        req.clear = bool(clear)

        future = self._set_robot_pose_cli.call_async(req)
        deadline = time.time() + self.SEND_GOAL_TIMEOUT_S
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False, "timeout"
        result = future.result()
        return bool(result.accepted), str(result.reason)

    # ----------------------------------------------------------- set_gazebo_pose (sim 디버그)

    def set_gazebo_pose_sync(
        self, x: float, y: float, yaw: float,
    ) -> tuple[bool, str]:
        """**sim 디버그 전용** — 가제보 entity 텔레포트.

        ``gogoping_msgs/srv/SetGazeboPose`` 동기 호출. 실물(Pi) 환경엔 server 없음 →
        ``(False, "service_unavailable")``. SW (blackboard) override 와는 별개 — admin
        UI 의 적용 버튼은 둘 다 호출 (set_robot_pose_sync + set_gazebo_pose_sync).
        """
        if not self._ros_ok or self._set_gazebo_pose_cli is None:
            return False, "bridge_not_started"

        if not self._set_gazebo_pose_cli.service_is_ready():
            if not self._set_gazebo_pose_cli.wait_for_service(timeout_sec=0.5):
                return False, "service_unavailable"

        from gogoping_msgs.srv import SetGazeboPose
        req = SetGazeboPose.Request()
        req.x = float(x)
        req.y = float(y)
        req.yaw = float(yaw)

        future = self._set_gazebo_pose_cli.call_async(req)
        deadline = time.time() + self.SEND_GOAL_TIMEOUT_S
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False, "timeout"
        result = future.result()
        return bool(result.accepted), str(result.reason)

    # ----------------------------------------------------------- emergency_stop

    def emergency_stop_sync(self) -> tuple[bool, str]:
        """긴급정지 — ``/gogoping/emergency_stop`` (std_srvs/Trigger) 동기 호출.

        gogoping_modes 의 command_listener 가 ``fsm.force_state("ERROR")`` 호출 →
        BT_error_main 빌드 → StopAllMotors (cmd_vel=0 + torque OFF).

        ERROR 는 terminal — 한 번 호출하면 robot 재시작해야 복구.
        idempotent — 이미 ERROR 면 modes 가 no-op 처리 (Trigger 응답: success=True).
        """
        if not self._ros_ok or self._estop_cli is None:
            return False, "bridge_not_started"

        if not self._estop_cli.service_is_ready():
            if not self._estop_cli.wait_for_service(timeout_sec=0.5):
                return False, "service_unavailable"

        from std_srvs.srv import Trigger
        req = Trigger.Request()

        future = self._estop_cli.call_async(req)
        deadline = time.time() + self.SEND_GOAL_TIMEOUT_S
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False, "timeout"
        result = future.result()
        return bool(result.success), str(result.message)

    # ----------------------------------------------------------- set_idle_timeout

    def set_idle_timeout_sync(self, seconds: float) -> tuple[bool, str]:
        """IDLE → RETURNING 자동 복귀 임계값 설정.

        gogoping_modes 노드의 ROS param ``idle_timeout_seconds`` 를 ``rcl_interfaces/
        SetParameters`` 로 변경. IdleTimeoutMonitor 의 ``on_set_parameters_callback``
        이 즉시 ``self._timeout_s`` + blackboard ``IDLE_TIMEOUT_SECONDS`` 갱신.

        반환: ``(accepted, reason)``. service 미가용 / param server 거부 시 False.
        """
        if not self._ros_ok or self._set_params_cli is None:
            return False, "bridge_not_started"

        if not self._set_params_cli.service_is_ready():
            if not self._set_params_cli.wait_for_service(timeout_sec=0.5):
                return False, "service_unavailable"

        from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
        from rcl_interfaces.srv import SetParameters

        req = SetParameters.Request()
        param = Parameter()
        param.name = "idle_timeout_seconds"
        param.value = ParameterValue(
            type=ParameterType.PARAMETER_DOUBLE,
            double_value=float(seconds),
        )
        req.parameters = [param]

        future = self._set_params_cli.call_async(req)
        deadline = time.time() + self.SEND_GOAL_TIMEOUT_S
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False, "timeout"
        result = future.result()
        # SetParameters 는 List[SetParametersResult] 반환 — 첫 결과만 본다 (1개만 보냄).
        if not result.results:
            return False, "no_result"
        r0 = result.results[0]
        return bool(r0.successful), str(r0.reason or "")

    # ----------------------------------------------------------- hideseek blackboard

    def _call_set_blackboard_sync(self, key: str, value: Any) -> tuple[bool, str]:
        """``SetBlackboard.srv`` 동기 호출 — allowlist 키만 허용.

        반환: ``(ok, reason)``. service 미가용 / server 거부 시 False.

        호출자는 asyncio handler — to_thread 로 오프로드해서 본 메서드의 blocking
        wait 가 event loop 를 막지 않게 한다.
        """
        if not self._ros_ok or self._set_blackboard_cli is None:
            return False, "bridge_not_started"

        if not self._set_blackboard_cli.service_is_ready():
            if not self._set_blackboard_cli.wait_for_service(timeout_sec=0.5):
                return False, "service_unavailable"

        from gogoping_msgs.srv import SetBlackboard
        req = SetBlackboard.Request()
        req.key = key
        try:
            req.value_json = json.dumps(value)
        except (TypeError, ValueError) as e:
            return False, f"json_encode_error: {e}"

        future = self._set_blackboard_cli.call_async(req)
        deadline = time.time() + self.SEND_GOAL_TIMEOUT_S
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False, "timeout"
        result = future.result()
        return bool(result.ok), str(result.reason or "")

    def write_hideseek_registered_ids(
        self, child_ids: list[int],
    ) -> tuple[bool, str]:
        """``hideseek_registered_ids`` blackboard 키를 set.

        robot-web RecruitPhase '출발' 버튼 → control-service handler 가 호출.
        BT 의 AwaitRecruitComplete 가 본 키 polling 해 SUCCESS → CountDown 단계로.

        부수효과: 본 호출은 새 round 시작 신호로 해석 — caught_ids 내부 누적 캐시도
        reset (다음 caught append 호출이 빈 set 부터 시작).
        """
        with self._hideseek_caught_lock:
            self._hideseek_caught_ids_cache = set()
        return self._call_set_blackboard_sync(
            BB_KEY_HIDESEEK_REGISTERED_IDS, list(child_ids),
        )

    def write_hideseek_patrol_only(self, value: bool) -> tuple[bool, str]:
        """``hideseek_patrol_only`` blackboard flag set.

        True → BT_hide_and_seek_sub 빌더가 patrol_sub 단독 (모집/카운트다운/이동/복귀 없이) 반환.
        False → 6-step Sequence 전체 (술래잡기 게임).

        admin UI [순찰] = True, robot UI [숨바꼭질] mode click = False (cleanup).
        BT 가 빌드되기 직전 (SetGoal 보다 먼저) 셋팅해야 builder 가 정확히 읽는다.
        """
        return self._call_set_blackboard_sync(
            BB_KEY_HIDESEEK_PATROL_ONLY, bool(value),
        )

    def write_hideseek_skip_countdown(self, value: bool = True) -> tuple[bool, str]:
        """``hideseek_skip_countdown`` blackboard flag set.

        Debug API /api/gogoping/play/hideseek/debug/skip-phase 가 countdown phase
        에서 호출. BT Countdown behaviour 가 다음 tick 에 이 flag True 면 즉시
        SUCCESS + flag 를 False 로 reset → 다음 카운트다운 진입 시 정상 30초.
        """
        return self._call_set_blackboard_sync(
            BB_KEY_HIDESEEK_SKIP_COUNTDOWN, bool(value),
        )

    def write_hideseek_caught_ids_complete(self) -> tuple[bool, str]:
        """``hideseek_caught_ids`` 를 누적 캐시 + registered_ids 와 동일 셋으로 set —
        CaughtMonitor 가 registered ⊆ caught 검사 → 즉시 SUCCESS → patrol/return
        parallel SUCCESS.

        Debug API /skip-phase 가 patrol/return phase 에서 호출. 실 round 의
        진짜 발견과 구분 안 됨 (snapshot 상 모두 caught) — 디버그 전용.
        """
        # registered_ids 는 snapshot 에서 못 읽음 (BT 가 publish 안 함). control-service
        # 의 in-process cache 도 caught_ids 만 유지. 안전한 가정:
        #   - 정상 흐름이면 BT 의 registered_ids 가 셋돼 있음 (recruit phase 완료 후)
        #   - 그 정확한 값을 알아야 ⊆ 만족 가능. 그렇지 않으면 dummy 큰 셋으로
        #     덮어쓰면 BT registered 가 그 셋 부분집합이 되어 SUCCESS.
        # 단순화: 매우 큰 sentinel set (1..100) — 일반적 child_id 범위 커버.
        sentinel_set = list(range(1, 101))
        with self._hideseek_caught_lock:
            self._hideseek_caught_ids_cache = set(sentinel_set)
        return self._call_set_blackboard_sync(
            BB_KEY_HIDESEEK_CAUGHT_IDS, sentinel_set,
        )

    def append_hideseek_caught_id(self, child_id: int) -> tuple[bool, str]:
        """``hideseek_caught_ids`` 에 ``child_id`` 추가 (cumulative set).

        robot-web PatrolPhase / ReturnPhase 인식 파이프라인이 호출. SetBlackboard.srv
        는 set 만 지원하므로 control-service 가 in-process 누적 set 을 유지하고
        매 호출마다 sorted list 전체를 셋팅한다.

        같은 child_id 중복 호출 무해 (set conversion). recruit-complete 호출 시
        본 캐시가 reset 되어 round 별로 분리된다.
        """
        with self._hideseek_caught_lock:
            self._hideseek_caught_ids_cache.add(int(child_id))
            ids = sorted(self._hideseek_caught_ids_cache)
        return self._call_set_blackboard_sync(
            BB_KEY_HIDESEEK_CAUGHT_IDS, ids,
        )

    # ----------------------------------------------------------- state pubsub

    def _on_state_msg(self, msg: Any) -> None:
        """``/gogoping/state`` 토픽 콜백 — JSON 파싱 후 캐시 + listener 호출."""
        try:
            payload = json.loads(msg.data)
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning(f"invalid state JSON: {e}")
            return
        with self._lock:
            self._latest_state = payload
            callbacks = list(self._state_callbacks)
        # callbacks 는 lock 밖에서 — listener 가 다시 register 호출해도 안전
        for cb in callbacks:
            try:
                cb(payload)
            except Exception as e:
                logger.warning(f"state callback 오류: {e}")

    def get_latest_state(self) -> dict | None:
        with self._lock:
            return self._latest_state

    def register_state_callback(self, fn: Callable[[dict], None]) -> Callable[[], None]:
        """state 변화 listener 등록. 반환된 함수로 unregister.

        주: 호출은 rclpy spin thread 에서 — asyncio loop 와 분리되어 있으므로 listener
        가 asyncio 객체를 만지려면 ``asyncio.run_coroutine_threadsafe`` 등 사용.
        """
        with self._lock:
            self._state_callbacks.append(fn)

        def unregister() -> None:
            with self._lock:
                try:
                    self._state_callbacks.remove(fn)
                except ValueError:
                    pass

        return unregister

    # ----------------------------------------------------------- nav event pubsub

    def _on_nav_event_msg(self, msg: Any) -> None:
        """``/gogoping/debug/nav_events`` 토픽 콜백 — JSON parse + ring buffer + listener."""
        try:
            payload = json.loads(msg.data)
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning(f"invalid nav_event JSON: {e}")
            return
        # 최소 필드 보강 (publisher 가 빠뜨려도 admin UI 가 깨지지 않게)
        payload.setdefault("ts", time.time())
        payload.setdefault("source", "?")
        payload.setdefault("level", "info")
        payload.setdefault("msg", "")
        with self._lock:
            self._nav_event_buffer.append(payload)
            callbacks = list(self._nav_event_callbacks)
        for cb in callbacks:
            try:
                cb(payload)
            except Exception as e:
                logger.warning(f"nav_event callback 오류: {e}")

    def get_recent_nav_events(self) -> list[dict]:
        """WS 연결 직후 backfill 용 — 최근 NAV_EVENT_BUFFER_SIZE 개."""
        with self._lock:
            return list(self._nav_event_buffer)

    def register_nav_event_callback(
        self, fn: Callable[[dict], None],
    ) -> Callable[[], None]:
        with self._lock:
            self._nav_event_callbacks.append(fn)

        def unregister() -> None:
            with self._lock:
                try:
                    self._nav_event_callbacks.remove(fn)
                except ValueError:
                    pass

        return unregister

    # ----------------------------------------------------------- ui_event 인젝션

    @staticmethod
    def _ui_event_to_msg(payload: dict) -> str:
        """``{"event": "lullaby_play", "src": "lullaby.mp3", "loop": True}`` →
        ``"event='lullaby_play' src='lullaby.mp3' loop=True"`` 한 줄.

        문자열 값은 ``!r`` (따옴표 포함), 그 외 타입은 그대로.
        """
        parts: list[str] = []
        for k, v in payload.items():
            if isinstance(v, str):
                parts.append(f"{k}={v!r}")
            else:
                parts.append(f"{k}={v}")
        return " ".join(parts)

    def _on_ui_event_msg(self, msg: Any) -> None:
        """``/gogoping/ui_event`` → nav_event 형태로 변환 후 ring buffer + listener.

        publish 가 아닌 *직접 callback 호출* — ui_event 는 robot-web 도 같은 토픽을 구독
        하므로 nav_events 로 republish 하면 양쪽에 중복 표시됨.
        """
        try:
            payload = json.loads(msg.data)
        except (json.JSONDecodeError, AttributeError) as e:
            logger.warning(f"invalid ui_event JSON: {e}")
            return
        nav_payload = {
            "ts": time.time(),
            "source": "UI",
            "level": "info",
            "msg": self._ui_event_to_msg(payload) if isinstance(payload, dict) else str(payload),
        }
        with self._lock:
            self._nav_event_buffer.append(nav_payload)
            callbacks = list(self._nav_event_callbacks)
        for cb in callbacks:
            try:
                cb(nav_payload)
            except Exception as e:
                logger.warning(f"ui_event → nav_event callback 오류: {e}")

    def _on_camera_pan_msg(self, msg: Any) -> None:
        """``/servo_bridge/cmd_pan`` (Float32 deg) → nav_event 변환 + 직접 listener 호출.

        Publisher: PanCameraSweep (BT) / CameraPanCard (admin UI) / keyboard_teleop.
        Subscriber: servo_bridge (모터 제어). 우리는 *로깅용* 추가 subscriber.
        """
        try:
            deg = float(msg.data)
        except (TypeError, ValueError, AttributeError):
            return
        nav_payload = {
            "ts": time.time(),
            "source": "CamPan",
            "level": "info",
            "msg": f"pan={deg:.1f}°",
        }
        with self._lock:
            self._nav_event_buffer.append(nav_payload)
            callbacks = list(self._nav_event_callbacks)
        for cb in callbacks:
            try:
                cb(nav_payload)
            except Exception as e:
                logger.warning(f"camera_pan → nav_event callback 오류: {e}")

    # ----------------------------------------------------------- admin UI 입력 publish

    def publish_admin_event(
        self, action: str, args: str = "", level: str = "info",
    ) -> None:
        """admin UI 가 누른 버튼/입력을 ``/gogoping/debug/nav_events`` 에 publish.

        ``source="AdminUI"`` 로 NavDebugLogCard 에 표시. self subscription 으로
        loopback 받아 ring buffer + WS 합류.

        bridge 가 아직 start() 안 했거나 ROS 미가용이면 silent no-op.
        """
        if self._nav_event_pub is None:
            return
        from std_msgs.msg import String
        payload = {
            "ts": time.time(),
            "source": "AdminUI",
            "level": level,
            "msg": f"{action} {args}".rstrip() if args else action,
        }
        try:
            out = String()
            out.data = json.dumps(payload, ensure_ascii=False)
            self._nav_event_pub.publish(out)
        except Exception as e:
            logger.warning(f"publish_admin_event 실패: {e}")

    # ----------------------------------------------------------- follow target

    def publish_follow_target(self, payload: dict) -> None:
        """교사 추종 시작 — FollowTarget 메시지 publish."""
        from gogoping_msgs.msg import FollowTarget
        msg = FollowTarget()
        msg.teacher_id = str(payload["teacher_id"])
        msg.teacher_name = payload.get("teacher_name", "")
        msg.embedding = list(payload["embedding"])
        msg.ts_ms = int(payload.get("ts_ms") or time.time() * 1000)
        self._follow_target_pub.publish(msg)

    def publish_follow_stop(self) -> None:
        """교사 추종 중지 — 빈 FollowTarget publish."""
        from gogoping_msgs.msg import FollowTarget
        msg = FollowTarget()
        msg.teacher_id = ""
        msg.teacher_name = ""
        msg.embedding = []
        msg.ts_ms = int(time.time() * 1000)
        self._follow_target_pub.publish(msg)

    _VALID_HINT_DIRECTIONS = frozenset({"left", "right", "front", "back", "search", "resume"})

    def publish_follow_hint(self, direction: str) -> None:
        """`/gogoping/follow_hint` (std_msgs/String) publish — follow_node WAITING_HINT 모드용.

        디버그 패널에서 left/right/front/back 버튼 클릭 시 호출. STT 미연동 시
        UI 에서 직접 발행.
        """
        if direction not in self._VALID_HINT_DIRECTIONS:
            raise ValueError(f"invalid direction: {direction!r}")
        if self._follow_hint_pub is None:
            raise BridgeUnavailable("follow_hint publisher not ready")
        from std_msgs.msg import String
        msg = String()
        msg.data = direction
        self._follow_hint_pub.publish(msg)

    def _on_follow_state(self, msg: Any) -> None:
        """/gogoping/follow_state 토픽 콜백 — follow_node mode 전이."""
        with self._lock:
            self._last_follow_state = msg.data
            callbacks = list(self._follow_state_callbacks)
        for cb in callbacks:
            try:
                cb(msg.data)
            except Exception:
                logger.exception("follow_state callback failed")

    def current_follow_state(self) -> str | None:
        """최근 follow_node mode (없으면 None)."""
        with self._lock:
            return self._last_follow_state

    def register_follow_state_callback(
        self, cb: Callable[[str], None],
    ) -> Callable[[], None]:
        """follow_state 가 갱신될 때마다 호출되는 callback 등록. unregister 함수 반환."""
        with self._lock:
            self._follow_state_callbacks.append(cb)

        def _unregister() -> None:
            with self._lock:
                if cb in self._follow_state_callbacks:
                    self._follow_state_callbacks.remove(cb)

        return _unregister

    def current_tracking_state(self) -> dict | None:
        """최근 TrackingState (없으면 None)."""
        with self._lock:
            return self._last_tracking_state

    def register_tracking_state_callback(
        self, cb: Callable[[dict], None],
    ) -> Callable[[], None]:
        """tracking_state dict 가 갱신될 때마다 호출되는 callback 등록.

        반환된 unregister 함수를 호출하면 등록 해제. 일반적으로 WS handler 가
        연결 시 register, 종료 시 unregister 한다.
        """
        with self._lock:
            self._tracking_state_callbacks.append(cb)

        def _unregister() -> None:
            with self._lock:
                if cb in self._tracking_state_callbacks:
                    self._tracking_state_callbacks.remove(cb)

        return _unregister

    def _on_tracking_state(self, msg: Any) -> None:
        """/gogoping/tracking_state 토픽 콜백."""
        distance = float(msg.distance_m)
        angle = float(msg.angle_deg)
        reid_sim = float(msg.reid_sim)
        state = {
            "active": msg.mode in ("searching", "tracking"),
            "matched": bool(msg.matched),
            "distance_m": distance if not math.isnan(distance) else None,
            "angle_deg": angle if not math.isnan(angle) else None,
            "bbox_size_px": int(msg.bbox_size_px) or None,
            "bbox_x1": int(msg.bbox_x1) or None,
            "bbox_y1": int(msg.bbox_y1) or None,
            "bbox_x2": int(msg.bbox_x2) or None,
            "bbox_y2": int(msg.bbox_y2) or None,
            "track_id": int(msg.track_id) or None,
            "reid_sim": reid_sim if not math.isnan(reid_sim) else None,
            "teacher_id": msg.teacher_id or None,
            # WS JSON 직렬화에 datetime 객체는 부담 — int ms 로 통일.
            "updated_at_ms": int(msg.ts_ms),
        }
        with self._lock:
            self._last_tracking_state = state
            callbacks = list(self._tracking_state_callbacks)
        # lock 해제 후 invoke — callback 안에서 다시 bridge 호출 시 deadlock 회피
        for cb in callbacks:
            try:
                cb(state)
            except Exception as e:  # noqa: BLE001
                try:
                    self._node.get_logger().warning(f"tracking_state callback error: {e}")
                except Exception:
                    pass


__all__ = [
    "GogopingRosBridge", "BridgeUnavailable", "ros_available",
    "TOPIC_STATE", "TOPIC_NAV_DEBUG_EVENTS",
    "SERVICE_SET_GOAL", "SERVICE_FORCE_STATE",
    "SERVICE_SET_BATTERY_LEVEL", "SERVICE_SET_ROBOT_POSE",
    "SERVICE_SET_GAZEBO_POSE", "SERVICE_EMERGENCY_STOP",
    "SERVICE_SET_BLACKBOARD",
    "BB_KEY_HIDESEEK_REGISTERED_IDS", "BB_KEY_HIDESEEK_CAUGHT_IDS",
]
