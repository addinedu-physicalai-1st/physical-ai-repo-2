"""양방향 teleop WS 브리지 (woobuntu — 실물 follower 머신).

control-service 와 단일 WebSocket 연결 (role=robot):
  수신  leader JSON  → /eduping/leader/joint_states (로컬 publish)
                       → leader_passthrough_node 가 구독해 JTC + 속도조절 → 실물 follower
  송신  /joint_states (실물 follower) → follower JSON → control-service
                       → doctor push loop → StateFrame → doctor 3D (three.js)

a-2 (eduping↔doctor ROS 도메인 분리) 에서 leader / follower joint 스트림은 ROS DDS
로 cross-machine 못 감 — 카메라·FSR 와 동일하게 WebSocket 으로 우회.

doctor three.js 는 반드시 이 노드가 올려보낸 실물 /joint_states 로 움직여야 함
(로컬 mock 아님) → 시뮬/실제 불일치 방지.

Wire format: 양방향 모두 JSON text — {"name": [...], "position": [...]}.

Params:
    control_url       (str,   default ws://localhost:8000)
    follower_topic    (str,   default /joint_states)
    leader_topic      (str,   default /eduping/leader/joint_states)
    follower_hz       (float, default 30.0)  follower 송신 throttle
"""
from __future__ import annotations

import json
import threading
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from websockets.sync.client import connect as ws_connect


PATH = "/ws/eduping/teleop?role=robot"


class TeleopWsRobot(Node):
    def __init__(self) -> None:
        super().__init__("teleop_ws_robot")

        self.declare_parameter("control_url", "ws://localhost:8000")
        self.declare_parameter("follower_topic", "/joint_states")
        self.declare_parameter("leader_topic", "/eduping/leader/joint_states")
        self.declare_parameter("follower_hz", 30.0)

        base = self.get_parameter("control_url").get_parameter_value().string_value
        self._url = base + PATH
        leader_topic = (
            self.get_parameter("leader_topic").get_parameter_value().string_value
        )
        follower_topic = (
            self.get_parameter("follower_topic").get_parameter_value().string_value
        )
        hz = float(self.get_parameter("follower_hz").get_parameter_value().double_value)
        self._min_period = 1.0 / max(0.1, hz)

        # 수신 leader → 로컬 publish.
        self._leader_pub = self.create_publisher(JointState, leader_topic, 10)
        # 송신 follower — /joint_states 구독.
        self.create_subscription(JointState, follower_topic, self._on_follower, 10)

        self._ws = None
        self._ws_lock = threading.Lock()
        self._last_send = 0.0
        self._stop = threading.Event()

        self._conn_thread = threading.Thread(
            target=self._conn_loop, name="teleop-robot-ws", daemon=True,
        )
        self._conn_thread.start()
        self.get_logger().info(
            f"teleop_ws_robot ↔ {self._url} (leader→{leader_topic}, {follower_topic}→follower)"
        )

    # ── WS 연결 + leader 수신 루프 ──────────────────────────────────────
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
                    for raw in ws:  # 수신 leader 프레임 (concurrent send 는 _on_follower)
                        self._on_leader_text(raw)
                except Exception:
                    pass
            except Exception as exc:
                self.get_logger().warn(f"WS connect failed: {exc}")
            with self._ws_lock:
                self._ws = None
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)

    def _on_leader_text(self, raw) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "ignore")
        try:
            obj = json.loads(raw)
            names = obj["name"]
            positions = obj["position"]
        except (ValueError, KeyError, TypeError):
            return
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = [str(n) for n in names]
        msg.position = [float(p) for p in positions]
        self._leader_pub.publish(msg)

    # ── follower /joint_states → WS 송신 ───────────────────────────────
    def _on_follower(self, msg: JointState) -> None:
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
    node = TeleopWsRobot()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
