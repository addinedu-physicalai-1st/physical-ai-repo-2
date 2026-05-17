"""ROS 2 bridge for GogoPing FSM/BT.

SetGoal.srv client + ``/gogoping/state`` topic subscriber. teleop / noriarm / eduping
ros_bridge.py 와 같은 패턴 — 별도 daemon thread 에서 rclpy spin, 모든 공유 상태 lock 보호.

asyncio (FastAPI) 핸들러는 본 모듈의 동기 메서드 (``send_goal_sync``, ``get_latest_state``,
``register_state_callback``) 만 호출 — rclpy API 직접 호출 금지.

ROS 환경 미source 시 ``ros_available() == False`` 반환 — 호출자가 503 응답 처리.
"""
from __future__ import annotations

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
SERVICE_SET_GOAL = "/gogoping/set_goal"


def ros_available() -> bool:
    """rclpy + gogoping_msgs import 가능 여부.

    ROS sourcing 안 됐거나 gogoping_msgs 빌드 전이면 False.
    """
    try:
        import rclpy  # noqa: F401
        from gogoping_msgs.srv import SetGoal  # noqa: F401
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
        self._ros_ok = False
        self._spin_thread: threading.Thread | None = None

        # rclpy 객체는 start() 에서만 생성 (테스트가 mock 으로 대체 가능)
        self._node: Any = None
        self._cli: Any = None      # SetGoal.srv client
        self._sub: Any = None      # /gogoping/state subscriber
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
        from gogoping_msgs.srv import SetGoal
        from std_msgs.msg import String

        if "ROS_DOMAIN_ID" not in os.environ:
            raise BridgeUnavailable(
                "ROS_DOMAIN_ID 환경변수 미설정 — 201~219 중 할당된 ID 사용"
            )

        # rclpy 가 이미 초기화되어 있을 수 있음 (다른 bridge 가 먼저 init).
        if not rclpy.ok():
            rclpy.init()

        self._node = rclpy.create_node("gogoping_control_bridge")
        self._cli = self._node.create_client(SetGoal, SERVICE_SET_GOAL)
        self._sub = self._node.create_subscription(
            String, TOPIC_STATE, self._on_state_msg, 10,
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


__all__ = [
    "GogopingRosBridge", "BridgeUnavailable", "ros_available",
    "TOPIC_STATE", "SERVICE_SET_GOAL",
]
