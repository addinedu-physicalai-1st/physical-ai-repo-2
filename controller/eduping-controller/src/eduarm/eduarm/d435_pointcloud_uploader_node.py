"""D435 PointCloud2 → 1m 필터/decimate/transform → WebSocket uploader.

흐름:
    /d435/depth/color/points  (ROS, 로컬)
        │
        ▼
    on_pointcloud callback
        │ 1m depth 필터 + 1/STRIDE decimation + optical→world 변환
        │ → flat float32 LE binary (uint32 count + xyz×N)
        ▼
    WebSocket client → control-service /ws/doctor/pointcloud?role=producer

Optical → world (REP-103):
    realsense optical: x=right, y=down, z=forward
    d435_link:         x=forward, y=left, z=up
    d435_link → world: static_tf (0.05, 0, 0.62), rpy=0
즉:
    x_world = z_optical + CAM_X
    y_world = -x_optical
    z_world = -y_optical + CAM_Z

Params:
    control_url       (str, default ws://localhost:8000)
    depth_limit_m     (float, default 1.0)
    point_stride      (int, default 4)
    throttle_hz       (float, default 5.0)
    max_points        (int, default 30000)
    cam_x / cam_y / cam_z (float)  static_tf 와 동기화 (doctor_teleop.launch.py)
"""
from __future__ import annotations

import math
import struct
import threading
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2 as pc2
from websockets.sync.client import connect as ws_connect


PATH = "/ws/doctor/pointcloud?role=producer"


def encode_points(points_xyz: list[tuple[float, float, float]]) -> bytes:
    n = len(points_xyz)
    out = bytearray(4 + n * 12)
    struct.pack_into("<I", out, 0, n)
    off = 4
    for x, y, z in points_xyz:
        struct.pack_into("<fff", out, off, x, y, z)
        off += 12
    return bytes(out)


class D435PointCloudUploader(Node):
    def __init__(self) -> None:
        super().__init__("d435_pointcloud_uploader")

        self.declare_parameter("control_url", "ws://localhost:8000")
        self.declare_parameter("depth_limit_m", 1.0)
        self.declare_parameter("point_stride", 4)
        self.declare_parameter("throttle_hz", 5.0)
        self.declare_parameter("max_points", 30000)
        self.declare_parameter("cam_x", 0.05)
        self.declare_parameter("cam_y", 0.0)
        self.declare_parameter("cam_z", 0.62)

        self._url = (
            self.get_parameter("control_url").get_parameter_value().string_value + PATH
        )
        self._depth_limit = float(
            self.get_parameter("depth_limit_m").get_parameter_value().double_value
        )
        self._stride = int(
            self.get_parameter("point_stride").get_parameter_value().integer_value
        )
        hz = float(self.get_parameter("throttle_hz").get_parameter_value().double_value)
        self._min_period = 1.0 / max(0.1, hz)
        self._max_points = int(
            self.get_parameter("max_points").get_parameter_value().integer_value
        )
        self._cx = float(self.get_parameter("cam_x").get_parameter_value().double_value)
        self._cy = float(self.get_parameter("cam_y").get_parameter_value().double_value)
        self._cz = float(self.get_parameter("cam_z").get_parameter_value().double_value)

        self._ws = None
        self._ws_lock = threading.Lock()
        self._last_send = 0.0
        self._stop = threading.Event()

        threading.Thread(
            target=self._conn_loop, name="pc-ws-conn", daemon=True,
        ).start()

        self.create_subscription(
            PointCloud2, "/d435/depth/color/points", self._on_pointcloud, 1,
        )
        self.get_logger().info(f"d435_pointcloud_uploader → {self._url}")

    def _conn_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                ws = ws_connect(self._url, max_size=None)
                with self._ws_lock:
                    self._ws = ws
                self.get_logger().info("WS connected")
                backoff = 1.0
                try:
                    for _ in ws:
                        pass
                except Exception:
                    pass
            except Exception as exc:
                self.get_logger().warn(f"WS connect failed: {exc}")
            with self._ws_lock:
                self._ws = None
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)

    def _filter_and_transform(self, points_iter) -> list[tuple[float, float, float]]:
        out: list[tuple[float, float, float]] = []
        limit = self._depth_limit
        skip = self._stride
        cap = self._max_points
        cx, cy, cz = self._cx, self._cy, self._cz
        idx = 0
        for p in points_iter:
            idx += 1
            if idx % skip != 0:
                continue
            x_opt, y_opt, z_opt = p[0], p[1], p[2]
            if not (0.0 < z_opt < limit):
                continue
            if math.isnan(x_opt) or math.isnan(y_opt):
                continue
            out.append((z_opt + cx, -x_opt + cy, -y_opt + cz))
            if len(out) >= cap:
                break
        return out

    def _on_pointcloud(self, msg: PointCloud2) -> None:
        now = time.monotonic()
        if now - self._last_send < self._min_period:
            return
        self._last_send = now
        with self._ws_lock:
            ws = self._ws
        if ws is None:
            return
        pts_iter = pc2.read_points(msg, field_names=("x", "y", "z"), skip_nans=False)
        world_pts = self._filter_and_transform(pts_iter)
        if not world_pts:
            return
        payload = encode_points(world_pts)
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
    node = D435PointCloudUploader()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
