"""교사 1인 검출/추적 — single-target YOLO + ReID.

단일 target embedding 과 가장 유사한 사람 1명만 찾아 반환. 프레임마다 독립
추론 + ReID 유사도 비교. IoU 트래커 / 갤러리 확장은 별도 perception 노드 분리 후
ByteTrack 으로 대체될 예정.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np

from gogoping_follow.config import (
    YOLO_MODEL_NAME,
    YOLO_CONF_THRESHOLD,
    YOLO_PERSON_CLASS_ID,
)


# 단일 detection 결과
@dataclass
class Detection:
    bbox: tuple[int, int, int, int]    # x1, y1, x2, y2 (px)
    confidence: float                  # YOLO confidence
    reid_sim: float                    # target embedding 과 코사인 sim ([-1, 1])
    crop: np.ndarray                   # BGR crop


# 매칭 임계값 — 이 값 이상이어야 target 으로 인정. 자녀 매칭 0.45 distance ≈ 0.55 cosine sim.
_REID_SIM_THRESHOLD = 0.55


class TeacherDetector:
    """target embedding 을 받고, 매 프레임 BGR 이미지에서 가장 유사한 사람을 반환."""

    def __init__(self) -> None:
        try:
            from ultralytics import YOLO  # noqa: WPS433
        except ImportError as exc:
            raise RuntimeError(
                "ultralytics(YOLO) 미설치 — `pip install ultralytics` 또는 follow_node 실행 환경 확인"
            ) from exc

        from gogoping_follow.reid_engine import ReIDEngine
        self._yolo = YOLO(YOLO_MODEL_NAME)
        self._reid = ReIDEngine()
        self._target_embedding: Optional[np.ndarray] = None

    def set_target(self, embedding: list[float] | np.ndarray) -> None:
        """추종 진입 시 target embedding 등록 (InsightFace 512-d, 또는 OSNet 차원)."""
        self._target_embedding = np.asarray(embedding, dtype=np.float32)

    def clear_target(self) -> None:
        self._target_embedding = None

    def has_target(self) -> bool:
        return self._target_embedding is not None

    def step(self, frame_bgr: np.ndarray) -> Optional[Detection]:
        """프레임 1장 처리. target 미설정이면 None, 사람 없거나 매칭 임계값 미만이면 None."""
        if self._target_embedding is None:
            return None

        results = self._yolo(
            frame_bgr,
            conf=YOLO_CONF_THRESHOLD,
            classes=[YOLO_PERSON_CLASS_ID],
            verbose=False,
        )

        best: Optional[Detection] = None
        best_sim = -1.0
        for r in results:
            for box in r.boxes:
                xyxy = box.xyxy[0].tolist()
                x1, y1, x2, y2 = (int(v) for v in xyxy)
                if x2 <= x1 or y2 <= y1:
                    continue
                crop = frame_bgr[y1:y2, x1:x2]
                if crop.size == 0:
                    continue
                feat = self._reid.extract_features(crop)
                sim = self._reid.compute_similarity(feat, self._target_embedding)
                if sim > best_sim:
                    best_sim = sim
                    best = Detection(
                        bbox=(x1, y1, x2, y2),
                        confidence=float(box.conf[0]),
                        reid_sim=float(sim),
                        crop=crop,
                    )

        if best is not None and best.reid_sim >= _REID_SIM_THRESHOLD:
            return best
        return None
