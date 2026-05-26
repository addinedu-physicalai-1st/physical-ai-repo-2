"""Doctor UI 용 pointcloud relay (D435 depth → three.js THREE.Points).

흐름:
    [EduPing 머신]
      realsense2_camera_node → /d435/depth/color/points (ROS, 로컬)
                                  │
                                  ▼
      d435_pointcloud_uploader_node (eduarm)
        1m 필터 + decimate + optical→world → flat float32 → WebSocket client
                            │
                            ▼  (cross-machine: WiFi/LAN, ~수백 KB/s)
    [Control 서버]
      /ws/doctor/pointcloud?role=producer ← uploader push
            │
            ▼
      PointCloudHub fan-out
            │
            ▼
      /ws/doctor/pointcloud?role=consumer ← portal-web three.js

Wire format (binary, little-endian):
    uint32 count
    float32 × 3 × count   (point xyz in world frame, m)

ROS DDS 로 PointCloud2 cross-machine 보내면 WiFi 부담 — WS 로 우회.
필터/decimate/transform 은 uploader (eduarm) 측에서 처리.
"""
from __future__ import annotations

import logging
import struct
from typing import Set

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

log = logging.getLogger(__name__)

DEPTH_LIMIT_M = 1.0       # optical z (=depth from camera) 이내만 포함.
POINT_STRIDE = 4          # 4 점마다 1점 (down-sample).
MAX_POINTS = 30000        # safety cap.

# 카메라 base offset (d435_link → world). doctor_teleop.launch.py 의
# static_tf_camera 와 동기화 필요.
CAM_X = 0.05
CAM_Y = 0.0
CAM_Z = 0.62


class PointCloudHub:
    """Decimated/filtered point cloud frame fan-out. producer 0~1, consumer N."""

    def __init__(self) -> None:
        self._producer: WebSocket | None = None
        self._consumers: Set[WebSocket] = set()
        self._last_frame: bytes | None = None

    async def register_producer(self, ws: WebSocket) -> None:
        prev = self._producer
        if prev is not None:
            try:
                await prev.close(code=status.WS_1000_NORMAL_CLOSURE)
            except Exception:
                pass
        self._producer = ws
        log.info("pointcloud producer registered")

    async def unregister_producer(self, ws: WebSocket) -> None:
        if self._producer is ws:
            self._producer = None
            log.info("pointcloud producer gone")

    async def register_consumer(self, ws: WebSocket) -> None:
        self._consumers.add(ws)
        last = self._last_frame
        if last is not None:
            try:
                await ws.send_bytes(last)
            except Exception as e:
                log.warning("pointcloud initial send failed: %s", e)

    async def unregister_consumer(self, ws: WebSocket) -> None:
        self._consumers.discard(ws)

    async def push_frame(self, frame: bytes) -> None:
        self._last_frame = frame
        dead: list[WebSocket] = []
        for ws in list(self._consumers):
            try:
                await ws.send_bytes(frame)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._consumers.discard(ws)


def encode_points(points_xyz: list[tuple[float, float, float]]) -> bytes:
    """flat float32 LE wire format. count uint32 + xyz floats."""
    n = len(points_xyz)
    out = bytearray(4 + n * 12)
    struct.pack_into("<I", out, 0, n)
    off = 4
    for x, y, z in points_xyz:
        struct.pack_into("<fff", out, off, x, y, z)
        off += 12
    return bytes(out)


def build_router(hub: PointCloudHub) -> APIRouter:
    r = APIRouter()

    @r.websocket("/ws/doctor/pointcloud")
    async def ws_handler(  # noqa: ANN202
        ws: WebSocket,
        role: str | None = Query(default=None),
    ) -> None:
        if role not in ("producer", "consumer"):
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.accept()
        try:
            if role == "producer":
                await hub.register_producer(ws)
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
                    payload = msg.get("bytes")
                    if payload:
                        await hub.push_frame(payload)
            else:
                await hub.register_consumer(ws)
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        break
        except WebSocketDisconnect:
            pass
        finally:
            if role == "producer":
                await hub.unregister_producer(ws)
            else:
                await hub.unregister_consumer(ws)

    return r
