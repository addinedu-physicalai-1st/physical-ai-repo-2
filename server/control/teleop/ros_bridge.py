"""ROS 2 bridge for teleop.

별도 daemon thread 에서 rclpy spin. 모든 공유 상태 (latest_odom, latest_scan,
last_cmd_age) 와 publish 는 단일 threading.Lock 으로 보호.

asyncio (FastAPI) 핸들러는 이 모듈의 동기 메서드만 호출 — rclpy API 직접 호출 금지.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any

# ROS topic 매핑 (테스트가 소스 grep 으로 검증)
TOPIC_CMD_VEL = "/gogoping/cmd_vel"
TOPIC_ODOM = "/gogoping/odom"
TOPIC_SCAN = "/gogoping/scan"


@dataclass
class OdomState:
    x: float
    y: float
    yaw: float
    vx: float
    wz: float
    received_at_s: float


@dataclass
class ScanState:
    angle_min: float
    angle_inc: float
    ranges: list[float]
    received_at_s: float


class RosBridge:
    """rclpy 노드를 들고 있고, 외부에는 thread-safe 한 동기 API 만 노출.

    AC #21~24 충족:
      - 모든 latest_state 갱신/publish 는 with self._lock 안에서.
      - rclpy.spin 호출은 _spin() 함수 1 곳, daemon Thread 에서만.
      - 외부 (asyncio) 는 rclpy API 직접 호출 금지 — 본 클래스의 메서드만.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest_odom: OdomState | None = None
        self._latest_scan: ScanState | None = None
        self._last_cmd_at_s: float | None = None
        self._ros_ok = False
        self._spin_thread: threading.Thread | None = None

        # rclpy 객체는 start() 에서만 생성 (테스트가 mock 으로 대체 가능)
        self._node: Any = None
        self._pub: Any = None
        self._executor: Any = None

    # ----------------------------------------------------------- lifecycle

    def start(self) -> None:
        """rclpy 노드 생성 + spin thread 시작.

        ROS_DOMAIN_ID 환경변수가 미설정이면 RuntimeError (AC #25).
        """
        if "ROS_DOMAIN_ID" not in os.environ:
            raise RuntimeError(
                "ROS_DOMAIN_ID 환경변수가 설정되지 않았습니다. "
                "201~219 중 할당된 ID 를 사용하세요."
            )

        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from geometry_msgs.msg import Twist
        from nav_msgs.msg import Odometry
        from sensor_msgs.msg import LaserScan

        if not rclpy.ok():
            rclpy.init()

        node = Node("teleop_bridge")
        self._pub = node.create_publisher(Twist, TOPIC_CMD_VEL, 10)
        node.create_subscription(
            Odometry, TOPIC_ODOM, self._on_odom, 10,
        )
        node.create_subscription(
            LaserScan, TOPIC_SCAN, self._on_scan, 10,
        )
        executor = SingleThreadedExecutor()
        executor.add_node(node)
        self._node = node
        self._executor = executor
        with self._lock:
            self._ros_ok = True

        thread = threading.Thread(
            target=self._spin, name="teleop-rclpy-spin", daemon=True,
        )
        self._spin_thread = thread
        thread.start()

    def _spin(self) -> None:
        """rclpy spin — 이 함수만 spin 호출 (AC #22)."""
        try:
            self._executor.spin()
        except Exception:
            pass

    def shutdown(self) -> None:
        try:
            if self._executor is not None:
                self._executor.shutdown()
            if self._node is not None:
                self._node.destroy_node()
        except Exception:
            pass

    # --------------------------------------------------------- subscribers

    # subscriber 콜백은 dict 갱신만, await/Queue.put/WebSocket.send 호출 0 (AC #28).
    def _on_odom(self, msg) -> None:
        # quaternion → yaw
        q = msg.pose.pose.orientation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        import math
        yaw = math.atan2(siny, cosy)
        state = OdomState(
            x=float(msg.pose.pose.position.x),
            y=float(msg.pose.pose.position.y),
            yaw=float(yaw),
            vx=float(msg.twist.twist.linear.x),
            wz=float(msg.twist.twist.angular.z),
            received_at_s=time.monotonic(),
        )
        with self._lock:
            self._latest_odom = state

    def _on_scan(self, msg) -> None:
        ranges = [float(r) for r in msg.ranges]
        state = ScanState(
            angle_min=float(msg.angle_min),
            angle_inc=float(msg.angle_increment),
            ranges=ranges,
            received_at_s=time.monotonic(),
        )
        with self._lock:
            self._latest_scan = state

    # ----------------------------------------------------------- public API

    def publish_cmd_vel(self, linear: float, angular: float) -> None:
        """Twist publish + last_cmd_at 갱신. lock 보호 (AC #21)."""
        with self._lock:
            if self._pub is None:
                return
            from geometry_msgs.msg import Twist
            msg = Twist()
            msg.linear.x = float(linear)
            msg.angular.z = float(angular)
            self._pub.publish(msg)
            self._last_cmd_at_s = time.monotonic()

    def snapshot(self) -> dict:
        """현재 상태의 immutable snapshot. asyncio 측에서 안전하게 호출."""
        with self._lock:
            now = time.monotonic()
            odom = None
            scan = None
            if self._latest_odom is not None:
                o = self._latest_odom
                odom = {"x": o.x, "y": o.y, "yaw": o.yaw,
                        "vx": o.vx, "wz": o.wz,
                        "age_ms": int((now - o.received_at_s) * 1000)}
            if self._latest_scan is not None:
                s = self._latest_scan
                scan = {"angle_min": s.angle_min,
                        "angle_inc": s.angle_inc,
                        "ranges": list(s.ranges),
                        "age_ms": int((now - s.received_at_s) * 1000)}
            last_cmd_age_ms = (
                None if self._last_cmd_at_s is None
                else int((now - self._last_cmd_at_s) * 1000)
            )
            return {
                "odom": odom,
                "scan": scan,
                "ros_ok": self._ros_ok,
                "last_cmd_age_ms": last_cmd_age_ms,
            }

    def health(self) -> dict:
        """/teleop/health endpoint 용 정보."""
        snap = self.snapshot()
        return {
            "ros_domain_id": int(os.environ.get("ROS_DOMAIN_ID", "0")),
            "last_odom_age_ms":
                None if snap["odom"] is None else snap["odom"]["age_ms"],
            "last_scan_age_ms":
                None if snap["scan"] is None else snap["scan"]["age_ms"],
            "ros_ok": snap["ros_ok"],
        }

    def last_cmd_age_s(self) -> float | None:
        with self._lock:
            if self._last_cmd_at_s is None:
                return None
            return time.monotonic() - self._last_cmd_at_s
