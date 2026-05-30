"""청진기 FSR → WebSocket uploader.

흐름:
    /eduping/stethoscope/fsr_raw  (ROS, 로컬)
        │
        ▼
    on_fsr callback → WebSocket client
        │
        ▼
    control-service /ws/eduping/stetho?role=producer

a-2 (eduping↔doctor ROS 도메인 분리) 에서 FSR 를 ROS DDS 로 cross-machine 보내면
도달 안 함 — 카메라(d435_rgb_uploader)와 동일하게 WebSocket 으로 우회.
같은 머신에선 localhost, cross-machine 일 땐 `control_url` 로 ws://server:8000.

Wire format: 텍스트 10진 정수 (raw ADC, 0..1023).

Params:
    control_url  (str, default ws://localhost:8000)  control-service base URL
    throttle_hz  (float, default 30.0)  최대 전송 속도 — doctor push loop 가 30Hz 라 그 이상 무의미
"""
from __future__ import annotations

import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Int32
from websockets.sync.client import connect as ws_connect


PATH = "/ws/eduping/stetho?role=producer"


class FsrWsUploader(Node):
    def __init__(self) -> None:
        super().__init__("fsr_ws_uploader")

        self.declare_parameter("control_url", "ws://localhost:8000")
        self.declare_parameter("throttle_hz", 30.0)

        self._url = (
            self.get_parameter("control_url").get_parameter_value().string_value + PATH
        )
        hz = float(self.get_parameter("throttle_hz").get_parameter_value().double_value)
        self._min_period = 1.0 / max(0.1, hz)

        self._ws = None
        self._ws_lock = threading.Lock()
        self._last_send = 0.0
        self._stop = threading.Event()

        # 별도 thread 가 WS 연결 + 재연결 관리. ROS callback 은 push only.
        self._conn_thread = threading.Thread(
            target=self._conn_loop, name="fsr-ws-conn", daemon=True,
        )
        self._conn_thread.start()

        self.create_subscription(Int32, "/eduping/stethoscope/fsr_raw", self._on_fsr, 10)
        self.get_logger().info(f"fsr_ws_uploader → {self._url}")

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
                        pass  # control-service 는 메시지 안 보냄
                except Exception:
                    pass
            except Exception as exc:
                self.get_logger().warn(f"WS connect failed: {exc}")
            with self._ws_lock:
                self._ws = None
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)

    def _on_fsr(self, msg: Int32) -> None:
        now = time.monotonic()
        if now - self._last_send < self._min_period:
            return
        self._last_send = now
        with self._ws_lock:
            ws = self._ws
        if ws is None:
            return
        try:
            ws.send(str(int(msg.data)))
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
    node = FsrWsUploader()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
