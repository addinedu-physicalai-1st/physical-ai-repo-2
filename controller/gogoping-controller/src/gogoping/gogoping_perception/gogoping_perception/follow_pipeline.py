"""FOLLOW 전용 추종 파이프라인 — ReID·enrollment·face matching·tracker.update.

주행(GOTO 등)엔 호출되지 않음 (perception_node 가 has_target 일 때만 process 호출).
ultralytics Results 는 받기만 함 — YOLO 호출은 yolo_runner 책임.
"""
from __future__ import annotations

import math
import os
import threading
import time

import numpy as np

from gogoping_msgs.msg import TrackingState
from gogoping_perception import config
from gogoping_perception.config import LOST_TIMEOUT_S
from gogoping_perception.depth_utils import bbox_depth_median
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


class FollowPipeline:
    def __init__(self, reid, tracker, logger):
        self._reid = reid
        self._tracker = tracker
        self._log = logger
        self._lock = threading.Lock()

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

    def has_target(self) -> bool:
        return self._tracker.has_target()

    @property
    def target_id(self):
        with self._lock:
            return self._last_track.track_id if self._last_track is not None else None

    def start_enrollment(self, face_emb, teacher_id, teacher_name) -> None:
        # 새 흐름: face emb 는 fallback 으로 보관, body emb 를 N frame 평균해 갱신.
        self._tracker.set_face_template(face_emb)
        self._tracker.start_enrollment(target_n=config.ENROLLMENT_N_FRAMES)
        self._enroll_face_retry_count = 0
        self._enroll_locked_track_id = None
        self._enroll_start_ts = time.time()
        self._log.info(
            f"Enrollment start: N={config.ENROLLMENT_N_FRAMES}, "
            f"face_threshold={config.ENROLLMENT_FACE_THRESHOLD}"
        )
        with self._lock:
            self._teacher_id = teacher_id
            # set 직후 LOST_TIMEOUT_S 동안은 mode="searching" 으로 머물도록 ts 초기화.
            # 0.0 으로 두면 첫 frame 도착 전 publish 가 바로 "lost" 로 나감.
            self._last_track_ts = time.time()
            self._last_track = None
        self._log.info(
            f"FollowTarget start: {teacher_name} ({teacher_id[:8]}...)"
        )

    def clear_target(self) -> None:
        with self._lock:
            self._teacher_id = ""
            self._last_track = None
            self._last_track_distance_mm = 0

    def process(self, results, color, depth) -> None:
        h, w = color.shape[:2]
        with self._lock:
            self._image_width = w

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
            d_med = bbox_depth_median(depth, bbox)
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
                    self._log.warn(f"face matching failed: {e}")
                    matched_idx = -1
                    sim = 0.0
                if matched_idx >= 0:
                    self._enroll_locked_track_id = bbox_meta[matched_idx][3]
                    self._log.info(
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
                        self._log.warn(
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
            self._log.warn("Enrollment timeout — forcing finalize")
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
            self._log.info(
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
            self._log.info(
                f"target: id={target.track_id} bbox={target.bbox} distance={d_med} mm "
                f"state={self._tracker.state} sim={self._tracker.last_sim}"
            )

    def build_tracking_state(self, now) -> TrackingState:
        msg = TrackingState()
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
        return msg
