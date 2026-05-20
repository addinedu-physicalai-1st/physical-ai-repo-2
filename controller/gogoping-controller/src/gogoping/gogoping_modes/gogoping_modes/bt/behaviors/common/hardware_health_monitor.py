"""HardwareHealthMonitor — LIDAR / odom staleness 감지 → ``fault`` trigger.

MVP 단계 모니터링 대상:
- LIDAR ``/gogoping/scan`` (``sensor_msgs/LaserScan``) — 끊기면 nav2 / 충돌 회피 불가
- odom ``/gogoping/odom`` (``nav_msgs/Odometry``) — 끊기면 pose 추정 / 추적 불가

각 토픽의 마지막 수신 시각이 ``hw_health_staleness_seconds`` (ROS param, 기본 3.0s) 보다
오래 전이면 ``fsm.trigger("fault", reason="lidar_timeout" | "odom_timeout")`` 발화.

향후 확장:
- ZLAC 모터 통신 끊김 — vicpinky_bringup 이 ``/gogoping/motor_health`` (diagnostic_msgs)
  publish 하면 추가. 현재는 bringup 에서 직접 검출 안 함.
- IMU staleness — IMU 도입 시 추가.

monitor 컨벤션 (``docs/conventions.md`` §2):
- 매 tick RUNNING 리턴 (SUCCESS/FAILURE 금지)
- edge-triggered — 1회 발화 후 ERROR terminal 이라 re-arm 불필요. ``initialise()`` 가
  새 트리 진입 시 호출되므로 ASSIST/PLAY/RETURNING 재진입 시 다시 발화 가능.
- ``initialise()`` 가 한 번도 메시지를 못 받은 토픽의 ``_last_*`` 를 *현재 시각* 으로
  세팅 → grace period (= staleness threshold) 이후에야 fault. 부팅 직후 false-positive 회피.
- 추가로 **process 부팅 grace** (``hw_health_startup_grace_seconds``, 기본 15s) 동안은
  fault 발화 자체를 보류. sim/실물 둘 다 LIDAR/odom 토픽 + bridge + nav2 가 다 떠서
  정상 메시지 흐름 안착하는 데 보통 5~10초 필요 — staleness 만으론 부족.
- 발화 전 ``blackboard.ERROR_REASON / ERROR_SOURCE`` 세팅 (admin UI / DB 로그 활용).

배치 (``docs/state-bt.md`` 정책):
- CHARGING / IDLE / ASSIST / PLAY / RETURNING / LOW_BATTERY_RETURN (6 트리)
- **MANUAL 제외** — battery/hw/collision 은 MANUAL 미배치 정책 (사용자 직접 제어 중
  자동 ERROR 차단). MapBoundaryMonitor 만 MANUAL 예외 배치.
- ERROR 제외 — terminal.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

import py_trees
from py_trees.common import Access, Status

from ...blackboard import Keys

if TYPE_CHECKING:
    from ....context import Context


class HardwareHealthMonitor(py_trees.behaviour.Behaviour):
    """LIDAR/odom staleness 감지 → fault(reason='lidar_timeout' / 'odom_timeout')."""

    TOPIC_LIDAR = "/gogoping/scan"
    TOPIC_ODOM = "/gogoping/odom"
    DEFAULT_STALENESS_S = 3.0
    DEFAULT_STARTUP_GRACE_S = 15.0
    PARAM_STALENESS = "hw_health_staleness_seconds"
    PARAM_STARTUP_GRACE = "hw_health_startup_grace_seconds"

    def __init__(self, name: str, context: "Context"):
        super().__init__(name)
        self.ctx = context
        self.bb = self.attach_blackboard_client(name=name)
        self.bb.register_key(key=Keys.ERROR_REASON, access=Access.WRITE)
        self.bb.register_key(key=Keys.ERROR_SOURCE, access=Access.WRITE)
        self._fired = False
        # subscriber 가 W (rclpy thread 에서 호출)
        self._last_lidar = 0.0
        self._last_odom = 0.0
        self._lidar_sub = None
        self._odom_sub = None
        self._staleness_s = self.DEFAULT_STALENESS_S
        self._startup_grace_s = self.DEFAULT_STARTUP_GRACE_S
        # process 부팅 시점 — startup grace 기준점. monitor 인스턴스가 트리 swap 마다
        # 새로 만들어져도 같은 process 면 같은 monotonic 시작점이라 OK.
        self._startup_time = time.monotonic()
        self._setup_done = False

    def setup(self, **kwargs) -> None:
        """py_trees 가 트리 setup 시 1회 호출 — ROS subscriber 등록 + param 읽기.

        py_trees.trees.BehaviourTree.setup(node=...) 가 kwargs 로 node 전달. 본 monitor
        는 ctx.node 를 그대로 사용해도 됨 (같은 노드).
        """
        if self._setup_done:
            return
        from nav_msgs.msg import Odometry
        from sensor_msgs.msg import LaserScan

        node = self.ctx.node
        # ROS param 으로 threshold override 가능 — launch arg / ros2 param set 둘 다 OK
        if not node.has_parameter(self.PARAM_STALENESS):
            node.declare_parameter(self.PARAM_STALENESS, self.DEFAULT_STALENESS_S)
        try:
            val = float(
                node.get_parameter(self.PARAM_STALENESS).get_parameter_value().double_value,
            )
            if val > 0.0:
                self._staleness_s = val
        except Exception:
            pass

        if not node.has_parameter(self.PARAM_STARTUP_GRACE):
            node.declare_parameter(
                self.PARAM_STARTUP_GRACE, self.DEFAULT_STARTUP_GRACE_S,
            )
        try:
            val = float(
                node.get_parameter(self.PARAM_STARTUP_GRACE).get_parameter_value().double_value,
            )
            if val >= 0.0:
                self._startup_grace_s = val
        except Exception:
            pass

        self._lidar_sub = node.create_subscription(
            LaserScan, self.TOPIC_LIDAR, self._on_lidar, 10,
        )
        self._odom_sub = node.create_subscription(
            Odometry, self.TOPIC_ODOM, self._on_odom, 10,
        )
        self._setup_done = True

    def initialise(self) -> None:
        # 새 트리 진입 시 staleness counter 리셋. 단 한 번도 수신 못 받은 토픽은
        # 이미 수신된 시각을 유지 — 실제로 staleness 계속 늘어나도록.
        # 부팅 직후 / 첫 트리 진입 시 _last_* == 0.0 → 현재 시각으로 초기화 (grace period).
        now = time.monotonic()
        if self._last_lidar == 0.0:
            self._last_lidar = now
        if self._last_odom == 0.0:
            self._last_odom = now
        self._fired = False

    def update(self) -> Status:
        if self._fired:
            return Status.RUNNING
        now = time.monotonic()
        # startup grace — process 부팅 직후 N초 동안은 fault 보류. sim/실물 동일.
        # LIDAR/odom 토픽 + bridge + nav2 가 다 안정화될 시간을 준다.
        if (now - self._startup_time) < self._startup_grace_s:
            return Status.RUNNING
        # LIDAR 우선 (안전상 더 critical). 동시에 둘 다 stale 이면 lidar 만 보고.
        if (now - self._last_lidar) > self._staleness_s:
            self._fire("lidar_timeout")
        elif (now - self._last_odom) > self._staleness_s:
            self._fire("odom_timeout")
        return Status.RUNNING

    def terminate(self, new_status: Status) -> None:
        # subscriber 는 ctx.node 라이프타임 동안 유지 — 트리 swap 마다 destroy 안 함.
        # 다음 트리 진입 시 initialise() 가 staleness counter 만 리셋.
        pass

    # --------------------------------------------------------------- ROS callbacks

    def _on_lidar(self, msg) -> None:
        self._last_lidar = time.monotonic()

    def _on_odom(self, msg) -> None:
        self._last_odom = time.monotonic()

    # --------------------------------------------------------------- internal

    def _fire(self, reason: str) -> None:
        self.bb.set(Keys.ERROR_REASON, reason)
        self.bb.set(Keys.ERROR_SOURCE, self.name)
        self.ctx.fsm.trigger("fault", reason=reason)
        self._fired = True
