"""Leader joint_states → control-service WebSocket uploader (doctor 머신).

흐름:
    /eduping/leader/joint_states  (ROS, 로컬 — feetech_leader_node)
        │
        ▼
    on_leader → WebSocket client (role=leader_src)
        │
        ▼
    control-service /ws/eduping/teleop?role=leader_src
        → active 일 때 woobuntu(role=robot) 로 forward

a-2 (eduping↔doctor ROS 도메인 분리) 에서 leader 를 ROS DDS 로 cross-machine
보내면 도달 안 함 — FSR(fsr_ws_uploader) 와 동일하게 WebSocket 으로 우회.

Wire format: JSON text — {"name": [...], "position": [...]}.

Params:
    control_url  (str,   default ws://localhost:8000)  control-service base URL
    throttle_hz  (float, default 50.0)                 최대 전송 속도
"""
from __future__ import annotations

import json
import threading
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from websockets.sync.client import connect as ws_connect


PATH = "/ws/eduping/teleop?role=leader_src"


class LeaderWsUploader(Node):
    def __init__(self) -> None:
        super().__init__("leader_ws_uploader")

        self.declare_parameter("control_url", "ws://localhost:8000")
        self.declare_parameter("throttle_hz", 50.0)

        self._url = (
            self.get_parameter("control_url").get_parameter_value().string_value + PATH
        )
        hz = float(self.get_parameter("throttle_hz").get_parameter_value().double_value)
        self._min_period = 1.0 / max(0.1, hz)

        self._ws = None
        self._ws_lock = threading.Lock()
        self._last_send = 0.0
        self._stop = threading.Event()

        self._conn_thread = threading.Thread(
            target=self._conn_loop, name="leader-ws-conn", daemon=True,
        )
        self._conn_thread.start()

        self.create_subscription(
            JointState, "/eduping/leader/joint_states", self._on_leader, 10
        )
        self.get_logger().info(f"leader_ws_uploader → {self._url}")

    def _conn_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                ws = ws_connect(self._url)
                with self._ws_lock:
                    self._ws = ws
                self.get_logger().info("WS connected")
                backoff = 1.0
                try:
                    for _ in ws:
                        pass  # control-service 는 leader_src 로 메시지 안 보냄
                except Exception:
                    pass
            except Exception as exc:
                self.get_logger().warn(f"WS connect failed: {exc}")
            with self._ws_lock:
                self._ws = None
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)

    def _on_leader(self, msg: JointState) -> None:
        now = time.monotonic()
        if now - self._last_send < self._min_period:
            return
        self._last_send = now
        with self._ws_lock:
            ws = self._ws
        if ws is None:
            return
        payload = json.dumps({
            "name": list(msg.name),
            "position": [float(p) for p in msg.position],
        })
        try:
            ws.send(payload)
        except Exception as exc:
            self.get_logger().debug(f"WS send failed (will reconnect): {exc}")

    def destroy_node(self) -> bool:
        self._stop.set()
        with self._ws_lock:
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None
        return super().destroy_node()


def main() -> None:
    rclpy.init()
    node = LeaderWsUploader()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
