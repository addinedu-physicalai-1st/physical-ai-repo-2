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
import os
import threading
import time
from typing import Any, Callable

from .mode_to_goal import Goal

logger = logging.getLogger(__name__)


# 토픽 / 서비스 이름 (gogoping_modes 와 일치 — 모두 /gogoping/* namespace)
TOPIC_STATE = "/gogoping/state"
TOPIC_NAV_DEBUG_EVENTS = "/gogoping/debug/nav_events"
SERVICE_SET_GOAL = "/gogoping/set_goal"
SERVICE_FORCE_STATE = "/gogoping/debug/force_state"
SERVICE_SET_BATTERY_LEVEL = "/gogoping/sim/set_battery_level"
SERVICE_SET_ROBOT_POSE = "/gogoping/debug/set_robot_pose"
SERVICE_SET_GAZEBO_POSE = "/gogoping/sim/teleport_pose"
SERVICE_EMERGENCY_STOP = "/gogoping/emergency_stop"

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
            ForceState, SetBatteryLevel, SetGazeboPose, SetGoal, SetRobotPose,
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
        self._sub: Any = None              # /gogoping/state subscriber
        self._nav_event_sub: Any = None    # /gogoping/debug/nav_events subscriber
        self._executor: Any = None

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
            ForceState, SetBatteryLevel, SetGazeboPose, SetGoal, SetRobotPose,
        )
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
        self._sub = self._node.create_subscription(
            String, TOPIC_STATE, self._on_state_msg, 10,
        )
        # nav cancel chain debug — admin UI NavDebugLogCard 가 WS 로 받음. depth=20
        # publisher 와 맞춰 burst 안 잃도록.
        self._nav_event_sub = self._node.create_subscription(
            String, TOPIC_NAV_DEBUG_EVENTS, self._on_nav_event_msg, 20,
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
        req.goal.mode = goal.mode
        req.goal.task = goal.task
        req.goal.carry_mode = goal.carry_mode
        req.goal.destination_key = goal.destination_key
        req.goal.target_id = goal.target_id

        future = self._cli.call_async(req)
        deadline = time.time() + self.SEND_GOAL_TIMEOUT_S
        while not future.done() and time.time() < deadline:
            time.sleep(0.01)
        if not future.done():
            return False, "timeout"
        result = future.result()
        return bool(result.accepted), str(result.reason)

    # ----------------------------------------------------------- force_state (디버그)

    def force_state_sync(
        self, target_state: str, sub_task: str = "",
    ) -> tuple[bool, str]:
        """**디버그 전용** — FSM 강제 state 전이.

        ``ForceState.srv`` 동기 호출. transition 규칙 우회.
        ``sub_task`` 비어있지 않으면 force_state 전에 blackboard 의 assist_task /
        play_task 세팅 — admin debug UI 의 sub combo box 가 채움.
        """
        if not self._ros_ok or self._force_state_cli is None:
            return False, "bridge_not_started"

        if not self._force_state_cli.service_is_ready():
            if not self._force_state_cli.wait_for_service(timeout_sec=0.5):
                return False, "service_unavailable"

        from gogoping_msgs.srv import ForceState
        req = ForceState.Request()
        req.target_state = target_state
        req.sub_task = sub_task

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


__all__ = [
    "GogopingRosBridge", "BridgeUnavailable", "ros_available",
    "TOPIC_STATE", "TOPIC_NAV_DEBUG_EVENTS",
    "SERVICE_SET_GOAL", "SERVICE_FORCE_STATE",
    "SERVICE_SET_BATTERY_LEVEL", "SERVICE_SET_ROBOT_POSE",
    "SERVICE_SET_GAZEBO_POSE", "SERVICE_EMERGENCY_STOP",
]
