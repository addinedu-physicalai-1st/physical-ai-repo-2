"""EduPing D435 depth+color → Control Server WS 송출 (ROS 구독 버전).

단일 opener 모델: 더 이상 pyrealsense2 로 장치를 직접 열지 않는다.
realsense2_camera(d435_camera.launch.py) 토픽을 구독해 동일 DepthFrame 을
/ws/depth-stream/producer/<robot> 로 송출. 와이어 포맷은 eduarm.depth_frame.
"""
from __future__ import annotations

import json
import threading
import time

import message_filters
import numpy as np
import rclpy
import zstandard as zstd
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
from websockets.sync.client import connect as ws_connect

from eduarm.depth_frame import ROBOT_IDS, Intr, build_depth_frame, encode_depth_frame

COLOR_TOPIC = "/d435/color/image_raw"
ALIGNED_DEPTH_TOPIC = "/d435/aligned_depth_to_color/image_raw"
COLOR_INFO_TOPIC = "/d435/color/camera_info"


class _WsProducer:
    """control-service WS producer + 재접속 데몬 (mugunghwa_perception 패턴)."""

    def __init__(self, url: str, logger, *, name: str = "depth-ws") -> None:
        self._url = url
        self._log = logger
        self._ws = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._loop, name=name, daemon=True).start()

    def _loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                ws = ws_connect(self._url, max_size=None)
                with self._lock:
                    self._ws = ws
                self._log.info(f"WS connected → {self._url}")
                backoff = 1.0
                try:
                    for _ in ws:  # 서버는 보내는 게 없음 — 끊김 감지용
                        pass
                except Exception:
                    pass
            except Exception as exc:
                self._log.warn(f"WS connect failed: {exc}")
            with self._lock:
                self._ws = None
            self._stop.wait(backoff)
            backoff = min(backoff * 2.0, 30.0)

    def send_bytes(self, payload: bytes) -> None:
        with self._lock:
            ws = self._ws
        if ws is None:
            return
        try:
            ws.send(payload)
        except Exception:
            pass

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            if self._ws:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._ws = None


class D435DepthStreamer(Node):
    def __init__(self) -> None:
        super().__init__("d435_depth_streamer")
        self.declare_parameter("server_host", "127.0.0.1")
        self.declare_parameter("server_port", 8100)
        self.declare_parameter("robot", "eduping")
        self.declare_parameter("jpeg_quality", 70)
        self.declare_parameter("throttle_hz", 15.0)

        gp = self.get_parameter
        host = gp("server_host").get_parameter_value().string_value
        port = int(gp("server_port").get_parameter_value().integer_value)
        self._robot = gp("robot").get_parameter_value().string_value
        self._robot_id = ROBOT_IDS[self._robot]
        self._quality = int(gp("jpeg_quality").get_parameter_value().integer_value)
        hz = float(gp("throttle_hz").get_parameter_value().double_value)
        self._min_period = 1.0 / max(0.1, hz)

        url = f"ws://{host}:{port}/ws/depth-stream/producer/{self._robot}"
        self._ws = _WsProducer(url, self.get_logger())
        self._bridge = CvBridge()
        self._compressor = zstd.ZstdCompressor(level=3)
        self._intr: Intr | None = None
        self._depth_scale = 0.001  # D435 기본 mm
        self._seq = 0
        self._last_send = 0.0

        self.create_subscription(CameraInfo, COLOR_INFO_TOPIC, self._on_info, 1)
        color_sub = message_filters.Subscriber(self, Image, COLOR_TOPIC)
        depth_sub = message_filters.Subscriber(self, Image, ALIGNED_DEPTH_TOPIC)
        self._sync = message_filters.ApproximateTimeSynchronizer(
            [color_sub, depth_sub], queue_size=5, slop=0.05,
        )
        self._sync.registerCallback(self._on_pair)
        self.get_logger().info(f"d435_depth_streamer up → {url}")

    def _on_info(self, msg: CameraInfo) -> None:
        # K = [fx 0 cx; 0 fy cy; 0 0 1]
        self._intr = Intr(fx=msg.k[0], fy=msg.k[4], cx=msg.k[2], cy=msg.k[5])

    def _on_pair(self, color_msg: Image, depth_msg: Image) -> None:
        now = time.monotonic()
        if now - self._last_send < self._min_period:
            return
        if self._intr is None:
            return  # intrinsics 아직 안 옴
        self._last_send = now
        try:
            color = self._bridge.imgmsg_to_cv2(color_msg, desired_encoding="bgr8")
            depth = self._bridge.imgmsg_to_cv2(depth_msg, desired_encoding="16UC1")
        except Exception as exc:
            self.get_logger().warn(f"cv_bridge failed: {exc}")
            return
        frame = build_depth_frame(
            np.ascontiguousarray(depth), color, self._intr, self._depth_scale,
            robot_id=self._robot_id, frame_seq=self._seq,
            ts_ms=int(time.time() * 1000), jpeg_quality=self._quality,
            compressor=self._compressor,
        )
        self._ws.send_bytes(encode_depth_frame(frame))
        self._seq = (self._seq + 1) & 0xFFFFFFFF

    def destroy_node(self) -> bool:
        self._ws.stop()
        return super().destroy_node()


def main() -> None:
    rclpy.init()
    node = D435DepthStreamer()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
