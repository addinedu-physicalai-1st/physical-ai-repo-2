"""gogoping_perception 노드 — shm 카메라 frame → /gogoping/tracking_state.

MultiThreadedExecutor + 2 callback group:
  target_cb  : /gogoping/follow_target 받아 set/clear_target
  publish_cb : 5 Hz timer — last_target 을 TrackingState 로 publish

영상 수신은 ShmReader (POSIX shared memory attach) — gogoping_camera 가 writer.
YOLOv8s + ByteTrack 은 ultralytics yolo.track(persist=True) 내장 사용.
ReID 는 OSNet x0.25 (gogoping_perception.reid_engine).
Depth fusion: bbox 중심 patch 의 median 으로 distance_mm 계산 (현재는 logger 출력).
"""
from __future__ import annotations

import math
import threading
import time
from typing import Optional

import numpy as np
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from gogoping_msgs.msg import FollowTarget, TrackingState

from gogoping_perception import config
from gogoping_perception.config import (
    LOST_TIMEOUT_S,
    TRACKER_NAME,
    TRACKING_STATE_HZ,
    YOLO_CONF_THRESHOLD,
    YOLO_DEVICE,
    YOLO_MODEL_NAME,
    YOLO_PERSON_CLASS,
)
from gogoping_perception.reid_engine import ReIDEngine
from gogoping_perception.shm_reader import ShmReader
from gogoping_perception.target_tracker import TargetTracker
from gogoping_perception.track import Track


# InsightFace lazy holder — first enrollment 시점에 load. 다른 process 와 중복 import 방지.
_face_app = None


def _get_face_app():
    """lazy-load InsightFace buffalo_l. 첫 호출 시 ~500MB-1GB VRAM."""
    global _face_app
    if _face_app is None:
        from insightface.app import FaceAnalysis  # local import — perception 외 contexts 에선 미사용
        app = FaceAnalysis(name='buffalo_l', allowed_modules=['detection', 'recognition'])
        # ctx_id=0 = GPU 0, -1 = CPU
        import os
        ctx_id = 0 if os.environ.get('PERCEPTION_FACE_CPU') != '1' else -1
        app.prepare(ctx_id=ctx_id, det_size=(640, 640))
        _face_app = app
    return _face_app


def _match_face_in_bboxes(
    face_app,
    color_bgr,
    boxes_xyxy,
    target_face_emb,
    threshold: float,
):
    """boxes_xyxy 의 각 bbox 안에서 face detection + matching.

    Returns
    -------
    (bbox_idx, sim): 매칭 성공 bbox 의 인덱스 + cosine sim. 매칭 실패 시 (-1, 0.0).
    """
    import numpy as np  # local
    best_idx = -1
    best_sim = -1.0
    target = np.asarray(target_face_emb, dtype=np.float32)
    target_norm = target / max(np.linalg.norm(target), 1e-8)
    for i, box in enumerate(boxes_xyxy):
        x1, y1, x2, y2 = map(int, box.tolist())
        crop = color_bgr[max(0, y1):y2, max(0, x1):x2]
        if crop.size == 0:
            continue
        faces = face_app.get(crop)
        if not faces:
            continue
        # 가장 큰 face 하나만
        f = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
        emb = f.normed_embedding  # already L2-normalized
        sim = float(np.dot(target_norm, emb))
        if sim > best_sim:
            best_sim = sim
            best_idx = i
    if best_sim >= threshold:
        return best_idx, best_sim
    return -1, best_sim


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
        # MediaPipe Pose 검증기 — bbox 별 사람/사물 판정 (사물 오인식 차단).
        from gogoping_perception.pose_validator import PoseValidator
        self._pose_validator = PoseValidator(
            enabled=config.POSE_ENABLED,
            min_visible_landmarks=config.POSE_MIN_VISIBLE_LANDMARKS,
            visibility_threshold=config.POSE_VISIBILITY_THRESHOLD,
            min_bbox_side_px=config.POSE_MIN_BBOX_SIDE_PX,
        )
        # pose 검증 통계 — 5초마다 로그.
        self._pose_stats_pass = 0
        self._pose_stats_fail = 0
        self._pose_stats_last_log = 0.0

        # imgsz — preset 에서 가져옴 (camera 패키지 PERCEPTION_PRESETS 와 동기).
        self._imgsz: int = config.PERCEPTION_PRESETS[config.ACTIVE_PRESET]["imgsz"]

        # shm reader + frame loop thread — 첫 FollowTarget 시 시작 (engines 와 동일 시점).
        self._reader: Optional[ShmReader] = None
        self._frame_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

        # state — frame loop 가 갱신, publish_cb 가 읽음. lock 보호.
        self._last_track: Track | None = None
        self._last_track_ts: float = 0.0
        self._last_track_distance_mm: int = 0  # D435 depth median (mm), 0 = invalid
        # [debug] sim 분포 로그 throttle — 5Hz (0.2s 간격) 로 ALL candidate sim 출력.
        # threshold 결정용 — 분포 데이터 충분히 모이면 이 로그 제거.
        self._sim_log_last_ts: float = 0.0
        self._teacher_id: str = ""
        self._image_width: int = 0

        # ── enrollment state (depth-aware ReID auto-enroll) ──
        # face matching 첫 frame retry 카운터.
        self._enroll_face_retry_count: int = 0
        # lock 된 enrollment 대상 track_id (face matching 통과 후 설정).
        self._enroll_locked_track_id: int | None = None
        # enrollment 시작 시각 — timeout 판정용.
        self._enroll_start_ts: float = 0.0

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

        # graph_router 심화 (2026-05-28) — state-driven YOLO 가동 + person_proximity publish
        from std_msgs.msg import Float32, String
        self._yolo_nav_modes = set(config.YOLO_NAV_MODES)
        self._current_state: str = "IDLE"
        self._person_proximity_pub = self.create_publisher(
            Float32, "/gogoping/person_proximity", 10,
        )
        self.create_subscription(
            String, "/gogoping/state_str", self._on_state_str, 10,
            callback_group=self._target_cbg,
        )

        # ── debug image publish (2026-05-29) — YOLO 박스 시각화 ──
        # rqt_image_view 로 /gogoping/perception/debug_image 구독하면 박스 확인 가능.
        # subscriber 없을 땐 draw/encode/publish 전부 skip → 평상시 오버헤드 0.
        # cv_bridge 미설치 환경에선 _debug_pub=None 으로 두고 perception 본기능은 유지.
        try:
            from sensor_msgs.msg import Image
            from cv_bridge import CvBridge
            self._bridge = CvBridge()
            self._debug_pub = self.create_publisher(
                Image, "/gogoping/perception/debug_image", 1,
            )
        except Exception as e:  # noqa: BLE001
            self._bridge = None
            self._debug_pub = None
            self.get_logger().warn(f"debug image publisher disabled: {e}")

        self.get_logger().info(
            "PerceptionNode initialized — waiting for FollowTarget "
            "(YOLO+ReID lazy-load on first target / state)"
        )

    # ---------- cleanup ----------
    def destroy_node(self):
        self._stop.set()
        if self._frame_thread is not None:
            self._frame_thread.join(timeout=2.0)
        if self._reader is not None:
            self._reader.close()
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
                f"Engines ready: YOLO={YOLO_MODEL_NAME} device={YOLO_DEVICE}, "
                f"ReID=OSNet, tracker={TRACKER_NAME}"
            )
            return True
        except Exception as e:  # noqa: BLE001
            self.get_logger().warn(f"Engine lazy-load failed: {e}")
            return False

    def _on_state_str(self, msg) -> None:
        """FSM state 변경 — nav 모드 진입 시 YOLO + frame loop 활성화.

        graph_router 의 사람 감지 정지·재개 로직이 perception 의
        /gogoping/person_proximity 토픽에 의존하므로, FOLLOW target 없이도
        nav 진행 중에는 YOLO 가 항상 돌고 있어야 한다.
        """
        new_state = str(msg.data)
        if new_state == self._current_state:
            return
        self._current_state = new_state
        if new_state in self._yolo_nav_modes:
            if self._yolo is None:
                ok = self._ensure_engines()
                if ok:
                    self.get_logger().info(
                        f"YOLO loaded (state={new_state})"
                    )
            self._ensure_frame_loop()

    def _ensure_frame_loop(self) -> None:
        """첫 FollowTarget 수신 시 shm reader attach + frame loop thread 시작."""
        if self._frame_thread is not None:
            return
        try:
            self._reader = ShmReader()
        except FileNotFoundError as e:
            self.get_logger().warn(
                f"shm attach failed: {e} — gogoping_camera writer 가 떠 있어야 합니다"
            )
            return
        except Exception as e:  # noqa: BLE001
            self.get_logger().warn(f"shm attach failed: {e}")
            return
        self._frame_thread = threading.Thread(
            target=self._frame_loop, name="perception-frame-loop", daemon=True,
        )
        self._frame_thread.start()
        self.get_logger().info("Shm frame loop thread started")

    # ---------- target_cb ----------
    def _on_follow_target(self, msg: FollowTarget) -> None:
        if not msg.teacher_id:
            with self._lock:
                self._teacher_id = ""
                self._last_track = None
                self._last_track_distance_mm = 0
            if self._tracker is not None:
                self._tracker.clear_target()
            self.get_logger().info("FollowTarget stop")
            return

        if not self._ensure_engines():
            self.get_logger().warn("Cannot start follow — engines unavailable")
            return

        assert self._tracker is not None  # _ensure_engines true 면 보장
        self._ensure_frame_loop()  # engines 준비 후 shm reader/frame loop 시작
        # 새 흐름: face emb 는 fallback 으로 보관, body emb 를 N frame 평균해 갱신.
        face_emb = np.asarray(list(msg.embedding), dtype=np.float32)
        self._tracker.set_face_template(face_emb)
        self._tracker.start_enrollment(target_n=config.ENROLLMENT_N_FRAMES)
        self._enroll_face_retry_count = 0
        self._enroll_locked_track_id = None
        self._enroll_start_ts = time.time()
        self.get_logger().info(
            f"Enrollment start: N={config.ENROLLMENT_N_FRAMES}, "
            f"face_threshold={config.ENROLLMENT_FACE_THRESHOLD}"
        )
        with self._lock:
            self._teacher_id = msg.teacher_id
            # set 직후 LOST_TIMEOUT_S 동안은 mode="searching" 으로 머물도록 ts 초기화.
            # 0.0 으로 두면 첫 frame 도착 전 publish 가 바로 "lost" 로 나감.
            self._last_track_ts = time.time()
            self._last_track = None
        self.get_logger().info(
            f"FollowTarget start: {msg.teacher_name} ({msg.teacher_id[:8]}...)"
        )

    # ---------- frame loop ----------
    def _frame_loop(self) -> None:
        """daemon thread — shm 에서 새 frame 을 poll 해서 _process_frame 호출."""
        assert self._reader is not None
        while not self._stop.is_set():
            try:
                snap = self._reader.poll(timeout=1.0)
            except Exception as e:  # noqa: BLE001
                self.get_logger().warn(f"shm poll failed: {e}")
                time.sleep(0.5)
                continue
            if snap is None:
                self.get_logger().warning("shm frame timeout — camera node alive?")
                continue
            self._process_frame(snap.color, snap.depth, snap.cap_ns)

    def _publish_person_proximity(self, results, depth: np.ndarray) -> None:
        """정면 박스 안 가장 가까운 사람 거리 publish.

        graph_router_node 의 사람 감지 정지 로직 (person_close) 트리거.
        결과 없거나 박스 밖이면 +inf publish.
        """
        from std_msgs.msg import Float32
        from gogoping_perception.frontal_box import nearest_person_in_box
        try:
            if not results:
                d_m = float("inf")
            else:
                r = results[0]
                if r.boxes is None or len(r.boxes.xyxy) == 0:
                    d_m = float("inf")
                else:
                    boxes_xyxy = r.boxes.xyxy.cpu().numpy()
                    detections = [
                        tuple(map(int, bbox.tolist())) for bbox in boxes_xyxy
                    ]
                    d_m = nearest_person_in_box(
                        detections=detections,
                        depth=depth,
                        fx=config.CAMERA_FX_PX,
                        cx=config.CAMERA_CX_PX,
                        box_forward_m=config.PERSON_FRONT_DIST_M,
                        box_lateral_m=config.PERSON_LATERAL_LIMIT_M,
                    )
            self._person_proximity_pub.publish(Float32(data=float(d_m)))
        except Exception as e:
            self.get_logger().warn(f"person_proximity publish failed: {e}")

    def _publish_debug_image(self, color: np.ndarray, depth: np.ndarray, results) -> None:
        """YOLO 박스를 그린 프레임을 /gogoping/perception/debug_image 로 publish.

        subscriber 가 없으면 즉시 return — draw/encode 비용 0.
        target track 은 초록 굵은 박스, 그 외는 주황 얇은 박스.
        라벨에 bbox depth median 거리(m) 표시 (얼굴 영역 patch — _bbox_depth_median).
        좌상단에 현재 FSM state 오버레이.
        """
        if self._debug_pub is None or self._debug_pub.get_subscription_count() == 0:
            return
        try:
            import cv2
            annotated = color.copy()
            with self._lock:
                target_id = (
                    self._last_track.track_id if self._last_track is not None else None
                )
            if results:
                r = results[0]
                if r.boxes is not None and len(r.boxes.xyxy) > 0:
                    xyxy = r.boxes.xyxy.cpu().numpy()
                    ids = (
                        r.boxes.id.cpu().numpy().astype(int)
                        if r.boxes.id is not None else None
                    )
                    confs = r.boxes.conf.cpu().numpy()
                    for i in range(len(xyxy)):
                        x1, y1, x2, y2 = map(int, xyxy[i].tolist())
                        tid = int(ids[i]) if ids is not None else -1
                        conf = float(confs[i])
                        is_target = target_id is not None and tid == target_id
                        box_color = (0, 255, 0) if is_target else (255, 160, 0)
                        thick = 3 if is_target else 1
                        cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, thick)
                        d_mm = self._bbox_depth_median(depth, (x1, y1, x2, y2))
                        dist = f" {d_mm / 1000.0:.2f}m" if d_mm > 0 else ""
                        label = f"people{dist}"
                        cv2.putText(
                            annotated, label, (x1, max(12, y1 - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 1, cv2.LINE_AA,
                        )
            cv2.putText(
                annotated, f"state={self._current_state}", (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2, cv2.LINE_AA,
            )
            msg = self._bridge.cv2_to_imgmsg(annotated, encoding="bgr8")
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = "camera_color_optical_frame"
            self._debug_pub.publish(msg)
        except Exception as e:  # noqa: BLE001
            self.get_logger().warn(f"debug image publish failed: {e}")

    @staticmethod
    def _bbox_depth_median(depth, bbox, patch=5):
        """bbox 상단 1/3 지점 (얼굴 영역) patch×patch median depth (mm). invalid 시 0.

        bbox 중심 (가슴/명치) 은 옷 두께·주름·IR 반사 노이즈로 실제보다 ~10cm 멀게
        측정됨. 얼굴은 IR 반사가 일정해 정확도 ↑. 얼굴 미검출 frame 에서도 bbox
        상단은 거의 항상 사람 머리·얼굴 영역.
        """
        x1, y1, x2, y2 = bbox
        cx = int((x1 + x2) / 2)
        # 중심 (y1+y2)/2 → 상단 1/3 (y1 + (y2-y1)/3) — 얼굴 위치에 해당.
        cy = int(y1 + (y2 - y1) / 3)
        r = patch // 2
        p = depth[max(0, cy - r): cy + r + 1, max(0, cx - r): cx + r + 1]
        v = p[(p >= config.DEPTH_MIN_MM) & (p <= config.DEPTH_MAX_MM)]
        return int(np.median(v)) if v.size else 0

    def _process_frame(self, color: np.ndarray, depth: np.ndarray, cap_ns: int) -> None:
        """YOLO + ByteTrack 추론 + depth fusion.

        color: 640×480×3 BGR uint8 (이미 ndarray — cv2.imdecode 불필요).
        depth: 640×480 uint16 (mm).

        Note: target 없어도 YOLO 추론은 수행 — graph_router 의 사람 감지용
        /gogoping/person_proximity 발화. tracker 로직만 target 있을 때 실행.
        """
        if self._yolo is None or self._tracker is None:
            return

        h, w = color.shape[:2]
        with self._lock:
            self._image_width = w

        # YOLO 추론 — ByteTrack(track_id) 은 추종(FOLLOW) target 있을 때만 필요.
        # 주행 중 사람감지(proximity)엔 ID 불필요 → predict 로 ByteTrack 오버헤드 제거.
        # (ByteTrack 비용은 화면 내 사람 수에 비례 — 빈 화면에선 predict≈track 이지만
        #  사람 여럿일 때만큼 절약. device 명시는 silent CPU 폴백 차단이 주목적.)
        try:
            if self._tracker.has_target():
                results = self._yolo.track(
                    color,
                    persist=True,
                    classes=[YOLO_PERSON_CLASS],
                    conf=YOLO_CONF_THRESHOLD,
                    imgsz=self._imgsz,
                    tracker=TRACKER_NAME,
                    device=YOLO_DEVICE,
                    verbose=False,
                )
            else:
                results = self._yolo.predict(
                    color,
                    classes=[YOLO_PERSON_CLASS],
                    conf=YOLO_CONF_THRESHOLD,
                    imgsz=self._imgsz,
                    device=YOLO_DEVICE,
                    verbose=False,
                )
        except Exception as e:  # noqa: BLE001
            self.get_logger().warn(f"yolo inference failed: {e}")
            return

        # ── person_proximity publish — target 유무 무관 (graph_router 용) ──
        self._publish_person_proximity(results, depth)


        # ── debug image publish — subscriber 있을 때만 (target 유무 무관) ──
        self._publish_debug_image(color, depth, results)

        # target 없으면 tracker 로직 skip — person_proximity 만 publish 하고 종료
        if not self._tracker.has_target():
            return

        if not results:
            return
        r = results[0]
        if r.boxes is None or r.boxes.id is None:
            return

        # ── all bboxes 의 OSNet emb (depth-aware mask 적용) ──
        boxes_xyxy = r.boxes.xyxy.cpu().numpy()
        boxes_id = r.boxes.id.cpu().numpy().astype(int)
        boxes_conf = r.boxes.conf.cpu().numpy()
        in_enrollment = (self._tracker.state == "ENROLLING")
        do_face_matching_this_frame = (
            in_enrollment
            and self._enroll_locked_track_id is None
            and self._enroll_face_retry_count < config.ENROLLMENT_FACE_RETRY_FRAMES
        )

        # 각 bbox 의 depth median + body embedding (mask 적용)
        bbox_meta: list[tuple] = []  # (bbox_xyxy, depth_median, emb, track_id, conf)
        for i in range(len(boxes_id)):
            x1, y1, x2, y2 = map(int, boxes_xyxy[i].tolist())
            crop_color = color[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
            crop_depth = depth[max(0, y1):min(h, y2), max(0, x1):min(w, x2)]
            if crop_color.size == 0:
                continue
            bbox = (x1, y1, x2, y2)

            # MediaPipe Pose 검증 — landmark 없는 bbox (사물) 는 ReID 단계로 안 감.
            pose_result = self._pose_validator.validate(crop_color, bbox)
            if not pose_result.is_person:
                self._pose_stats_fail += 1
                continue
            self._pose_stats_pass += 1

            d_med = self._bbox_depth_median(depth, bbox)
            assert self._reid is not None
            if d_med > 0 and crop_depth.size > 0:
                emb = self._reid.extract_with_mask(
                    crop_color, crop_depth, d_med,
                    tolerance_mm=config.DEPTH_MASK_TOLERANCE_MM,
                    min_valid_ratio=config.DEPTH_MASK_MIN_VALID_RATIO,
                )
            else:
                emb = self._reid.extract_features(crop_color)
            bbox_meta.append((bbox, d_med, emb, int(boxes_id[i]), float(boxes_conf[i])))

        # pose 검증 통계 — 5초마다 로그.
        now_pose = time.time()
        if now_pose - self._pose_stats_last_log >= 5.0:
            total = self._pose_stats_pass + self._pose_stats_fail
            if total > 0:
                self.get_logger().info(
                    f"[pose] pass={self._pose_stats_pass} fail={self._pose_stats_fail} "
                    f"({100 * self._pose_stats_fail / total:.0f}% bbox 차단)"
                )
            self._pose_stats_pass = 0
            self._pose_stats_fail = 0
            self._pose_stats_last_log = now_pose

        # ── enrollment 첫 frame face matching ──
        if do_face_matching_this_frame and bbox_meta:
            face_template = self._tracker._face_template  # type: ignore[attr-defined]
            if face_template is not None and face_template.size > 0:
                try:
                    face_app = _get_face_app()
                    boxes_np = np.stack([np.array(b[0]) for b in bbox_meta])
                    matched_idx, sim = _match_face_in_bboxes(
                        face_app, color, boxes_np, face_template,
                        threshold=config.ENROLLMENT_FACE_THRESHOLD,
                    )
                except Exception as e:  # noqa: BLE001
                    self.get_logger().warn(f"face matching failed: {e}")
                    matched_idx = -1
                    sim = 0.0
                if matched_idx >= 0:
                    self._enroll_locked_track_id = bbox_meta[matched_idx][3]
                    self.get_logger().info(
                        f"Enrollment lock: track_id={self._enroll_locked_track_id} face_sim={sim:.3f}"
                    )
                else:
                    self._enroll_face_retry_count += 1
                    if self._enroll_face_retry_count >= config.ENROLLMENT_FACE_RETRY_FRAMES:
                        # fallback: largest bbox 1회
                        biggest = max(
                            bbox_meta,
                            key=lambda b: (b[0][2] - b[0][0]) * (b[0][3] - b[0][1]),
                        )
                        self._enroll_locked_track_id = biggest[3]
                        self.get_logger().warn(
                            f"Enrollment fallback (face retry exhausted): "
                            f"largest bbox track_id={self._enroll_locked_track_id}"
                        )

        # ── ENROLLING 중 lock 된 track 의 body emb accumulate ──
        if in_enrollment and self._enroll_locked_track_id is not None:
            for bbox, d_med, emb, track_id, _conf in bbox_meta:
                if track_id == self._enroll_locked_track_id:
                    self._tracker.accumulate_body(emb)
                    break

        # ── enrollment timeout — force finalize ──
        if (
            in_enrollment
            and (time.time() - self._enroll_start_ts) > config.ENROLLMENT_TIMEOUT_S
            and self._tracker.state == "ENROLLING"
        ):
            self.get_logger().warn("Enrollment timeout — forcing finalize")
            self._tracker.finalize_enrollment(force=True)

        # ── 일반 매칭 (ACTIVE) — bbox_meta 를 Track 리스트로 변환 후 update ──
        # d_med 도 함께 — drift 재매칭 시 거리 연속성 검사에 사용.
        tracks: list[Track] = []
        for bbox, d_med, emb, track_id, conf in bbox_meta:
            tracks.append(Track(
                track_id=track_id, bbox=bbox, embedding=emb, conf=conf,
                distance_mm=int(d_med),
            ))

        target = self._tracker.update(tracks)

        # [debug] sim 분포 로그 — 5Hz throttle. threshold 결정용 데이터 수집.
        # 형식: [sim-dist] target=<tid|none> n=<count> sims={id=A:0.74, id=B:0.12, ...}
        # 데이터 충분히 모이면 이 블록 제거.
        now_ts = time.time()
        if (now_ts - self._sim_log_last_ts) >= 0.2 and self._tracker.all_sims:
            self._sim_log_last_ts = now_ts
            tgt_id = target.track_id if target is not None else None
            sims_str = ", ".join(
                f"id={tid}:{s:.2f}" for tid, s in self._tracker.all_sims
            )
            self.get_logger().info(
                f"[sim-dist] target={tgt_id} n={len(self._tracker.all_sims)} "
                f"sims={{{sims_str}}}"
            )

        if target is not None:
            # target 은 위 tracks 리스트에서 온 Track — distance_mm 에 이미 같은 bbox 의
            # depth median 이 들어있다 (Track(distance_mm=int(d_med))). 재계산 불필요.
            d_med = target.distance_mm
            with self._lock:
                self._last_track = target
                self._last_track_ts = time.time()
                self._last_track_distance_mm = d_med
            self.get_logger().info(
                f"target: id={target.track_id} bbox={target.bbox} distance={d_med} mm "
                f"state={self._tracker.state} sim={self._tracker.last_sim}"
            )

    # ---------- publish_cb ----------
    def _tick_publish(self) -> None:
        msg = TrackingState()
        now = time.time()
        with self._lock:
            track = self._last_track
            ts = self._last_track_ts
            distance_mm = self._last_track_distance_mm
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

        # D435 depth fusion — bbox 중심 patch median (mm) → m. invalid 시 NaN.
        # LiDAR fusion 은 Phase B (실 빅핀키 + LiDAR) 에서 합산 예정.
        msg.distance_m = float(distance_mm) / 1000.0 if distance_mm > 0 else float("nan")
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
