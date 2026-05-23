"""gogoping_perception 노드 — WS /ws/video-stream → /gogoping/tracking_state.

MultiThreadedExecutor + 2 callback group:
  target_cb  : /gogoping/follow_target 받아 set/clear_target
  publish_cb : 5 Hz timer — last_target 을 TrackingState 로 publish

영상 수신은 WSVideoClient (daemon thread + asyncio loop) 가 담당.
YOLOv8s + ByteTrack 은 ultralytics yolo.track(persist=True) 내장 사용.
ReID 는 OSNet x0.25 (gogoping_perception.reid_engine).
"""
from __future__ import annotations

import asyncio
import math
import threading
import time
from typing import Optional

import cv2
import numpy as np
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from gogoping_msgs.msg import FollowTarget, TrackingState

from gogoping_perception.config import (
    LOST_TIMEOUT_S,
    TRACKER_NAME,
    TRACKING_STATE_HZ,
    YOLO_CONF_THRESHOLD,
    YOLO_DEVICE,
    YOLO_IMG_SIZE,
    YOLO_MODEL_NAME,
    YOLO_PERSON_CLASS,
)
from gogoping_perception.reid_engine import ReIDEngine
from gogoping_perception.target_tracker import TargetTracker
from gogoping_perception.track import Track
from gogoping_perception.ws_video_client import WSVideoClient


class PerceptionNode(Node):
    def __init__(self) -> None:
        super().__init__("gogoping_perception_node")
        self._lock = threading.Lock()

        # callback group 분리 — publish/target_cb 가 서로 막지 않게.
        self._target_cbg = ReentrantCallbackGroup()
        self._publish_cbg = ReentrantCallbackGroup()

        # lazy-load — ultralytics + torchreid 무거우니 첫 target 시 init.
        self._yolo = None
        self._reid: ReIDEngine | None = None
        self._tracker: TargetTracker | None = None

        # WS video client (daemon thread + asyncio loop) — 첫 FollowTarget 시 시작.
        self._ws_client: Optional[WSVideoClient] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_loop: Optional[asyncio.AbstractEventLoop] = None

        # state — _on_ws_frame 이 갱신, publish_cb 가 읽음. lock 보호.
        self._last_track: Track | None = None
        self._last_track_ts: float = 0.0
        self._teacher_id: str = ""
        self._image_width: int = 0

        self.create_subscription(
            FollowTarget, "/gogoping/follow_target", self._on_follow_target, 10,
            callback_group=self._target_cbg,
        )
        self._state_pub = self.create_publisher(
            TrackingState, "/gogoping/tracking_state", 10,
        )
        self.create_timer(
            1.0 / TRACKING_STATE_HZ, self._tick_publish,
            callback_group=self._publish_cbg,
        )

        self.get_logger().info(
            "PerceptionNode initialized — waiting for FollowTarget "
            "(YOLO+ReID lazy-load on first target)"
        )

    # ---------- cleanup ----------
    def destroy_node(self):
        if self._ws_client is not None:
            self._ws_client.stop()
        if self._ws_loop is not None and self._ws_loop.is_running():
            self._ws_loop.call_soon_threadsafe(self._ws_loop.stop)
        super().destroy_node()

    # ---------- lazy init ----------
    def _ensure_engines(self) -> bool:
        if self._yolo is not None and self._reid is not None and self._tracker is not None:
            return True
        try:
            from ultralytics import YOLO  # noqa: WPS433 — lazy
            self._yolo = YOLO(YOLO_MODEL_NAME)
            self._reid = ReIDEngine(device=YOLO_DEVICE)
            self._tracker = TargetTracker(self._reid)
            self.get_logger().info(
                f"Engines ready: YOLO={YOLO_MODEL_NAME}, ReID=OSNet, tracker={TRACKER_NAME}"
            )
            return True
        except Exception as e:  # noqa: BLE001
            self.get_logger().warn(f"Engine lazy-load failed: {e}")
            return False

    def _ensure_ws_client(self) -> None:
        """첫 FollowTarget 수신 시 WS client 시작 (engines lazy load 와 동일 시점)."""
        if self._ws_thread is not None:
            return
        self._ws_client = WSVideoClient(
            frame_callback=self._on_ws_frame,
            logger=self.get_logger(),
        )
        self._ws_thread = threading.Thread(
            target=self._run_ws_loop, name="perception_ws_client", daemon=True,
        )
        self._ws_thread.start()
        self.get_logger().info("WS video client thread started")

    def _run_ws_loop(self) -> None:
        assert self._ws_client is not None
        self._ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._ws_loop)
        try:
            self._ws_loop.run_until_complete(self._ws_client.run())
        finally:
            self._ws_loop.close()

    # ---------- target_cb ----------
    def _on_follow_target(self, msg: FollowTarget) -> None:
        if not msg.teacher_id:
            with self._lock:
                self._teacher_id = ""
                self._last_track = None
            if self._tracker is not None:
                self._tracker.clear_target()
            self.get_logger().info("FollowTarget stop")
            return

        if not self._ensure_engines():
            self.get_logger().warn("Cannot start follow — engines unavailable")
            return

        assert self._tracker is not None  # _ensure_engines true 면 보장
        self._ensure_ws_client()  # engines 준비 후 WS client 시작
        self._tracker.set_target(list(msg.embedding))
        with self._lock:
            self._teacher_id = msg.teacher_id
            # set 직후 LOST_TIMEOUT_S 동안은 mode="searching" 으로 머물도록 ts 초기화.
            # 0.0 으로 두면 첫 frame 도착 전 publish 가 바로 "lost" 로 나감.
            self._last_track_ts = time.time()
            self._last_track = None
        self.get_logger().info(
            f"FollowTarget start: {msg.teacher_name} ({msg.teacher_id[:8]}...)"
        )

    # ---------- ws frame callback ----------
    def _on_ws_frame(self, jpeg: bytes, frame_seq: int, ts_ms: int) -> None:
        """WS thread (asyncio) 에서 호출. lock 보호로 inference + state 갱신.

        기존 _on_image (ROS Image subscription) 의 inference 로직을 그대로 이식하되,
        sensor_msgs/Image → cv2 변환 부분만 cv2.imdecode 로 교체.
        """
        if self._yolo is None or self._tracker is None or not self._tracker.has_target():
            return
        try:
            arr = np.frombuffer(jpeg, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception as e:  # noqa: BLE001
            self.get_logger().warn(f"JPEG decode failed: {e}")
            return
        if frame is None:
            return

        h, w = frame.shape[:2]
        with self._lock:
            self._image_width = w

        # ultralytics yolo.track — ByteTrack 통합. persist=True 로 track_id 유지.
        try:
            results = self._yolo.track(
                frame,
                persist=True,
                classes=[YOLO_PERSON_CLASS],
                conf=YOLO_CONF_THRESHOLD,
                imgsz=YOLO_IMG_SIZE,
                tracker=TRACKER_NAME,
                verbose=False,
            )
        except Exception as e:  # noqa: BLE001
            self.get_logger().warn(f"yolo.track failed: {e}")
            return

        if not results:
            return
        r = results[0]
        if r.boxes is None or r.boxes.id is None:
            return

        # multi-target → Track 리스트 (embedding 계산)
        tracks: list[Track] = []
        boxes_xyxy = r.boxes.xyxy.cpu().numpy()
        boxes_id = r.boxes.id.cpu().numpy().astype(int)
        boxes_conf = r.boxes.conf.cpu().numpy()
        for i in range(len(boxes_id)):
            x1, y1, x2, y2 = map(int, boxes_xyxy[i].tolist())
            crop = frame[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
            if crop.size == 0:
                continue
            assert self._reid is not None
            emb = self._reid.extract_features(crop)
            tracks.append(Track(
                track_id=int(boxes_id[i]),
                bbox=(x1, y1, x2, y2),
                embedding=emb,
                conf=float(boxes_conf[i]),
            ))

        # target 식별 — track_id 유지 우선, drift 시 ReID 재매칭
        target = self._tracker.update(tracks)
        if target is not None:
            with self._lock:
                self._last_track = target
                self._last_track_ts = time.time()

    # ---------- publish_cb ----------
    def _tick_publish(self) -> None:
        msg = TrackingState()
        now = time.time()
        with self._lock:
            track = self._last_track
            ts = self._last_track_ts
            teacher_id = self._teacher_id
            image_w = self._image_width

        has_target = self._tracker is not None and self._tracker.has_target()

        if not has_target:
            msg.mode = "idle"
            msg.matched = False
        elif track is not None and (now - ts) < LOST_TIMEOUT_S:
            msg.mode = "tracking"
            msg.matched = True
        else:
            msg.mode = "searching" if (now - ts) < LOST_TIMEOUT_S * 2 else "lost"
            msg.matched = False

        msg.distance_m = float("nan")  # LiDAR fusion 은 follow_node 책임 (현재는 NaN)
        if track is not None and msg.matched:
            x1, y1, x2, y2 = track.bbox
            cx = (x1 + x2) / 2.0
            # bbox center → 카메라 frame 방위. 카메라 intrinsics 기반 정확화는 후속.
            if image_w > 0:
                offset_px = (image_w / 2.0) - cx
                msg.angle_deg = float(offset_px * 0.1)
            else:
                msg.angle_deg = float("nan")
            msg.bbox_size_px = int(math.sqrt(max(1, (x2 - x1) * (y2 - y1))))
            msg.bbox_x1 = int(x1)
            msg.bbox_y1 = int(y1)
            msg.bbox_x2 = int(x2)
            msg.bbox_y2 = int(y2)
            msg.track_id = int(track.track_id)
            sim = self._tracker.last_sim if self._tracker is not None else None
            msg.reid_sim = float(sim) if sim is not None else float("nan")
        else:
            msg.angle_deg = float("nan")
            msg.bbox_size_px = 0
            msg.bbox_x1 = 0
            msg.bbox_y1 = 0
            msg.bbox_x2 = 0
            msg.bbox_y2 = 0
            msg.track_id = 0
            msg.reid_sim = float("nan")

        msg.teacher_id = teacher_id
        msg.ts_ms = int(now * 1000)
        self._state_pub.publish(msg)


def main() -> None:
    rclpy.init()
    node = PerceptionNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
