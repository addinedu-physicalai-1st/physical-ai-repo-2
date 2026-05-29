"""MediaPipe BlazePose 기반 사람 검증 — bbox 안에 사람 keypoint 가 있는지 판정.

YOLO 의 bbox 만으로는 마네킹/인형/의자 같은 사물도 사람으로 잡힌다. Pose 는 사람
33-landmark detector 라 사물에선 visibility 가 거의 안 나오므로, visible landmark
≥ MIN 일 때만 사람으로 판정해 사물 오인식을 차단한다.

호출자: perception_node 의 bbox 처리 루프 (crop_color 를 받아 validate).

설계:
- static_image_mode=True — bbox crop 마다 독립 검출 (multi-person 호환).
- model_complexity=0 (lite) — CPU 추론 ~5~10ms/bbox.
- mediapipe 미설치 시 init_failed=True → 항상 통과 (서비스 중단 X).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PoseResult:
    is_person: bool
    n_visible: int             # visibility ≥ threshold 인 landmark 갯수
    skipped_reason: str = ""   # "disabled" | "too_small" | "empty_crop" | "infer_error" | ""


def is_bbox_too_small(bbox: tuple[int, int, int, int], min_side_px: int) -> bool:
    x1, y1, x2, y2 = bbox
    return (x2 - x1) < min_side_px or (y2 - y1) < min_side_px


def count_visible_landmarks(landmarks: object, visibility_threshold: float) -> int:
    """NormalizedLandmarkList.landmark 중 visibility ≥ threshold 인 갯수."""
    if landmarks is None:
        return 0
    return sum(1 for lm in landmarks.landmark if lm.visibility >= visibility_threshold)


class PoseValidator:
    """MediaPipe Pose 인스턴스 wrapper.

    enabled=False 또는 mediapipe 미설치 시 항상 통과 (안전 fallback).
    """

    def __init__(
        self,
        *,
        enabled: bool,
        min_visible_landmarks: int,
        visibility_threshold: float,
        min_bbox_side_px: int,
    ) -> None:
        self._enabled = enabled
        self._min_visible = min_visible_landmarks
        self._visibility_threshold = visibility_threshold
        self._min_bbox_side = min_bbox_side_px
        self._pose = None
        self._init_failed = False

        if not enabled:
            return
        try:
            import mediapipe as mp
            self._pose = mp.solutions.pose.Pose(
                static_image_mode=True,
                model_complexity=0,
                enable_segmentation=False,
                min_detection_confidence=0.5,
            )
        except Exception:  # noqa: BLE001
            self._init_failed = True

    def validate(
        self, crop_color: np.ndarray, bbox: tuple[int, int, int, int],
    ) -> PoseResult:
        if not self._enabled or self._init_failed:
            return PoseResult(is_person=True, n_visible=0, skipped_reason="disabled")
        if is_bbox_too_small(bbox, self._min_bbox_side):
            # 멀리 있는 사람 보호 — 너무 작은 bbox 는 검증 skip 후 통과.
            return PoseResult(is_person=True, n_visible=0, skipped_reason="too_small")
        if crop_color.size == 0 or self._pose is None:
            return PoseResult(is_person=True, n_visible=0, skipped_reason="empty_crop")

        try:
            rgb = crop_color[:, :, ::-1]  # OpenCV BGR → RGB
            results = self._pose.process(rgb)
        except Exception:  # noqa: BLE001 — drop frame on inference error
            return PoseResult(is_person=True, n_visible=0, skipped_reason="infer_error")

        n_visible = count_visible_landmarks(
            results.pose_landmarks, self._visibility_threshold,
        )
        return PoseResult(
            is_person=(n_visible >= self._min_visible),
            n_visible=n_visible,
        )

    def close(self) -> None:
        if self._pose is not None:
            self._pose.close()
            self._pose = None
