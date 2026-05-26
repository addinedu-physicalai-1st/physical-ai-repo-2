"""D435 PointCloud2 → 1m 필터/decimate/TF 변환 → WebSocket uploader.

흐름:
    /d435/depth/color/points  (ROS, 로컬)
        │
        ▼
    on_pointcloud callback
        │ depth 필터 (msg frame Z < limit) + 1/STRIDE decimation
        │ tf2 lookup(world ← msg.header.frame_id) → 4x4 행렬 적용
        │ → flat float32 LE binary (uint32 count + xyz×N)
        ▼
    WebSocket client → control-service /ws/doctor/pointcloud?role=producer

Transform 은 TF tree 에서 lookup — static_tf_camera (doctor_teleop.launch.py) 의
cam_pitch/yaw/roll 등 어떤 변경이든 자동 반영.

Params:
    control_url       (str, default ws://localhost:8000)
    depth_limit_m     (float, default 1.0)  optical Z (=depth) 기준
    point_stride      (int, default 4)
    throttle_hz       (float, default 15.0)
    max_points        (int, default 30000)
"""
from __future__ import annotations

import math
import struct
import threading
import time

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2 as pc2
from std_msgs.msg import Float32MultiArray, MultiArrayDimension
from tf2_ros import Buffer, TransformListener, TransformException
from websockets.sync.client import connect as ws_connect


WORLD_FRAME = "world"

# Self-filter — D435 가 자기 robot 의 팔/몸을 obstacle 로 잡지 않게 voxel 제거.
# 각 link 원점 중심 + 반경 SELF_FILTER_RADIUS 의 sphere 안 voxel 은 skip.
SELF_FILTER_LINKS = (
    "openarm_body_link0",
    *(f"openarm_left_link{i}" for i in range(8)),    # link0~7
    *(f"openarm_right_link{i}" for i in range(8)),
    "openarm_left_hand",
    "openarm_right_hand",
)
SELF_FILTER_RADIUS = 0.10        # 10cm — 팔 두께 + 여유.


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
        self.declare_parameter("throttle_hz", 15.0)
        self.declare_parameter("max_points", 30000)

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

        self._ws = None
        self._ws_lock = threading.Lock()
        self._last_send = 0.0
        self._stop = threading.Event()

        # TF lookup 으로 optical → world 변환. cam_pitch/yaw/roll 모두 반영됨.
        self._tf_buffer = Buffer()
        self._tf_listener = TransformListener(self._tf_buffer, self)

        threading.Thread(
            target=self._conn_loop, name="pc-ws-conn", daemon=True,
        ).start()

        # collision-aware velocity scaling 용 ROS publisher.
        # 같은 voxel 데이터를 ROS 토픽으로도 노출 — leader_passthrough_node 가 sub.
        self._voxel_pub = self.create_publisher(
            Float32MultiArray, "/eduping/world_voxels", 1,
        )

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

    def _lookup_self_centers(self) -> np.ndarray | None:
        """추적해야 할 robot link 들의 world 좌표 (N, 3). TF 미준비 link 는 skip."""
        centers: list[tuple[float, float, float]] = []
        for link in SELF_FILTER_LINKS:
            try:
                t = self._tf_buffer.lookup_transform(
                    WORLD_FRAME, link, rclpy.time.Time(),
                )
            except TransformException:
                continue
            tr = t.transform.translation
            centers.append((tr.x, tr.y, tr.z))
        if not centers:
            return None
        return np.asarray(centers, dtype=np.float32)

    def _lookup_transform_matrix(self, src_frame: str) -> np.ndarray | None:
        """world ← src_frame 4x4 동차 변환 행렬. TF 미준비면 None."""
        try:
            t = self._tf_buffer.lookup_transform(
                WORLD_FRAME, src_frame, rclpy.time.Time(),
            )
        except TransformException:
            return None
        tr = t.transform.translation
        rot = t.transform.rotation
        # quaternion → rotation matrix
        x, y, z, w = rot.x, rot.y, rot.z, rot.w
        xx, yy, zz = x * x, y * y, z * z
        xy, xz, yz = x * y, x * z, y * z
        wx, wy, wz = w * x, w * y, w * z
        R = np.array([
            [1 - 2 * (yy + zz), 2 * (xy - wz),     2 * (xz + wy)],
            [2 * (xy + wz),     1 - 2 * (xx + zz), 2 * (yz - wx)],
            [2 * (xz - wy),     2 * (yz + wx),     1 - 2 * (xx + yy)],
        ], dtype=np.float32)
        T = np.eye(4, dtype=np.float32)
        T[:3, :3] = R
        T[:3, 3] = (tr.x, tr.y, tr.z)
        return T

    def _filter_and_transform(
        self,
        points_iter,
        T_world_src: np.ndarray,
        self_centers: np.ndarray | None,
    ) -> list[tuple[float, float, float]]:
        """optical points → depth filter + stride → world → self-filter."""
        # 1) depth filter + stride.
        limit = self._depth_limit
        skip = self._stride
        cap = self._max_points
        kept: list[tuple[float, float, float]] = []
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
            kept.append((x_opt, y_opt, z_opt))
            if len(kept) >= cap:
                break
        if not kept:
            return []
        # 2) world 변환.
        arr = np.asarray(kept, dtype=np.float32)
        homo = np.hstack([arr, np.ones((arr.shape[0], 1), dtype=np.float32)])
        world = (homo @ T_world_src.T)[:, :3]            # (N, 3)
        # 3) self-filter — robot link 주변 voxel 제거.
        if self_centers is not None and self_centers.shape[0] > 0:
            # (N, M, 3) → (N, M) → (N,)  vectorized squared distance.
            diffs = world[:, None, :] - self_centers[None, :, :]
            min_d_sq = (diffs * diffs).sum(axis=2).min(axis=1)
            mask = min_d_sq > (SELF_FILTER_RADIUS * SELF_FILTER_RADIUS)
            world = world[mask]
        return [(float(r[0]), float(r[1]), float(r[2])) for r in world]

    def _on_pointcloud(self, msg: PointCloud2) -> None:
        now = time.monotonic()
        if now - self._last_send < self._min_period:
            return
        self._last_send = now

        T = self._lookup_transform_matrix(msg.header.frame_id)
        if T is None:
            return  # TF 아직 안 옴 — 다음 frame 에서 시도.

        self_centers = self._lookup_self_centers()
        pts_iter = pc2.read_points(msg, field_names=("x", "y", "z"), skip_nans=False)
        world_pts = self._filter_and_transform(pts_iter, T, self_centers)
        if not world_pts:
            return

        # ROS topic publish — collision check 용.
        ros_msg = Float32MultiArray()
        ros_msg.layout.dim = [
            MultiArrayDimension(label="points", size=len(world_pts), stride=3),
            MultiArrayDimension(label="xyz", size=3, stride=1),
        ]
        flat: list[float] = []
        for p in world_pts:
            flat.extend(p)
        ros_msg.data = flat
        self._voxel_pub.publish(ros_msg)

        # WS send — doctor UI three.js 용.
        with self._ws_lock:
            ws = self._ws
        if ws is None:
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
