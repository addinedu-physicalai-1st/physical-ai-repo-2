"""ROS 2 bridge for camera pan/tilt teleop.

Mirrors teleop/ros_bridge.py: daemon thread runs rclpy spin, sync API for
asyncio callers (publish_pan/publish_tilt/snapshot/health). Subscribes to
/servo_bridge/state (sensor_msgs/JointState) to echo the live angle back to
the UI; publishes std_msgs/Float32 on /servo_bridge/cmd_pan and
/servo_bridge/cmd_tilt for the gogoping_camera_pan node to consume.

No watchdog here — the Arduino firmware has its own 1s timeout and the
servo_bridge ROS node re-sends the latest setpoint at 20Hz, so a missed
HTTP POST does not snap the camera back to center.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any

TOPIC_CMD_PAN = "/servo_bridge/cmd_pan"
TOPIC_CMD_TILT = "/servo_bridge/cmd_tilt"
TOPIC_STATE = "/servo_bridge/state"

PAN_JOINT = "camera_pan_joint"
TILT_JOINT = "camera_tilt_joint"


@dataclass
class CamState:
    pan_deg: float
    tilt_deg: float
    received_at_s: float


class CameraPanBridge:
    """rclpy 노드 보유, 외부에는 thread-safe sync API 만 노출.

    teleop.RosBridge 와 동일한 컨벤션:
    - 모든 latest_state / publish 는 self._lock 안에서.
    - rclpy.spin 은 _spin() 한 곳, daemon Thread.
    - 외부 (asyncio) 에서 rclpy API 직접 호출 금지.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: CamState | None = None
        self._ros_ok = False
        self._spin_thread: threading.Thread | None = None

        self._node: Any = None
        self._pub_pan: Any = None
        self._pub_tilt: Any = None
        self._executor: Any = None

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> None:
        if "ROS_DOMAIN_ID" not in os.environ:
            raise RuntimeError(
                "ROS_DOMAIN_ID 환경변수가 설정되지 않았습니다. "
                "201~219 중 할당된 ID 를 사용하세요."
            )

        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.node import Node
        from sensor_msgs.msg import JointState
        from std_msgs.msg import Float32

        if not rclpy.ok():
            rclpy.init()

        node = Node("camera_pan_bridge")
        self._pub_pan = node.create_publisher(Float32, TOPIC_CMD_PAN, 10)
        self._pub_tilt = node.create_publisher(Float32, TOPIC_CMD_TILT, 10)
        node.create_subscription(JointState, TOPIC_STATE, self._on_state, 10)

        executor = SingleThreadedExecutor()
        executor.add_node(node)
        self._node = node
        self._executor = executor
        with self._lock:
            self._ros_ok = True

        thread = threading.Thread(
            target=self._spin, name="camera-pan-rclpy-spin", daemon=True,
        )
        self._spin_thread = thread
        thread.start()

    def _spin(self) -> None:
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

    # ── subscribers ──────────────────────────────────────────────────────────
    def _on_state(self, msg) -> None:
        """JointState (name=[pan,tilt], position=[..]) → CamState."""
        pan = tilt = None
        try:
            names = list(msg.name)
            positions = list(msg.position)
            if PAN_JOINT in names:
                pan = float(positions[names.index(PAN_JOINT)])
            if TILT_JOINT in names:
                tilt = float(positions[names.index(TILT_JOINT)])
        except (IndexError, ValueError):
            return
        if pan is None or tilt is None:
            return
        state = CamState(pan_deg=pan, tilt_deg=tilt, received_at_s=time.monotonic())
        with self._lock:
            self._latest = state

    # ── public API ───────────────────────────────────────────────────────────
    def publish_pan(self, deg: float) -> None:
        with self._lock:
            if self._pub_pan is None:
                return
            from std_msgs.msg import Float32
            msg = Float32()
            msg.data = float(deg)
            self._pub_pan.publish(msg)

    def publish_tilt(self, deg: float) -> None:
        with self._lock:
            if self._pub_tilt is None:
                return
            from std_msgs.msg import Float32
            msg = Float32()
            msg.data = float(deg)
            self._pub_tilt.publish(msg)

    def snapshot(self) -> dict:
        with self._lock:
            now = time.monotonic()
            if self._latest is None:
                return {
                    "pan_deg": None,
                    "tilt_deg": None,
                    "age_ms": None,
                    "ros_ok": self._ros_ok,
                }
            s = self._latest
            return {
                "pan_deg": s.pan_deg,
                "tilt_deg": s.tilt_deg,
                "age_ms": int((now - s.received_at_s) * 1000),
                "ros_ok": self._ros_ok,
            }

    def health(self) -> dict:
        snap = self.snapshot()
        return {
            "ros_domain_id": int(os.environ.get("ROS_DOMAIN_ID", "0")),
            "ros_ok": snap["ros_ok"],
            "last_state_age_ms": snap["age_ms"],
        }
