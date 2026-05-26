"""D435 RGB → WebSocket uploader.

흐름:
    /d435/color/image_raw  (ROS, 로컬)
        │
        ▼
    on_image callback
        │ cv_bridge → JPEG (cv2.imencode)
        ▼
    WebSocket client → control-service /ws/eduping/rgb?role=producer

같은 머신에선 localhost, cross-machine 일 땐 `control_url` param 으로 ws://server:8000.

Params:
    control_url   (str, default ws://localhost:8000)  control-service base URL
    jpeg_quality  (int, default 75)
    throttle_hz   (float, default 15.0)  최대 publish 속도 — D435 native 15 이상이면 의미 없음
"""
from __future__ import annotations

import json
import threading
import time

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image
from websockets.sync.client import connect as ws_connect


PATH = "/ws/eduping/rgb?role=producer"


class D435RgbUploader(Node):
    def __init__(self) -> None:
        super().__init__("d435_rgb_uploader")

        self.declare_parameter("control_url", "ws://localhost:8000")
        self.declare_parameter("jpeg_quality", 75)
        self.declare_parameter("throttle_hz", 15.0)

        self._url = (
            self.get_parameter("control_url").get_parameter_value().string_value
            + PATH
        )
        self._quality = int(
            self.get_parameter("jpeg_quality").get_parameter_value().integer_value
        )
        hz = float(self.get_parameter("throttle_hz").get_parameter_value().double_value)
        self._min_period = 1.0 / max(0.1, hz)

        self._bridge = CvBridge()
        self._ws = None
        self._ws_lock = threading.Lock()
        self._last_send = 0.0
        self._stop = threading.Event()

        # 별도 thread 가 WS 연결 + 재연결 관리. ROS callback 은 그냥 push only.
        self._conn_thread = threading.Thread(
            target=self._conn_loop, name="rgb-ws-conn", daemon=True,
        )
        self._conn_thread.start()

        self.create_subscription(Image, "/d435/color/image_raw", self._on_image, 1)
        self.get_logger().info(f"d435_rgb_uploader → {self._url}")

    def _conn_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                ws = ws_connect(self._url, max_size=None)
                with self._ws_lock:
                    self._ws = ws
                self.get_logger().info("WS connected")
                backoff = 1.0
                # 그냥 살아있게만. close 까지 block.
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

    def _on_image(self, msg: Image) -> None:
        now = time.monotonic()
        if now - self._last_send < self._min_period:
            return
        self._last_send = now
        try:
            bgr = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().warn(f"cv_bridge failed: {exc}")
            return
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, self._quality])
        if not ok:
            return
        with self._ws_lock:
            ws = self._ws
        if ws is None:
            return
        try:
            ws.send(buf.tobytes())
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
    node = D435RgbUploader()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    _ = json  # silence
    main()
