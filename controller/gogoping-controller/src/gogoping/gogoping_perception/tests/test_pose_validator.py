"""pose_validator pure-function + 동작 검증 tests.

mediapipe 가 없는 환경 호환 — disabled / init_failed 경로 검증.
실 모델 호출 테스트는 mediapipe 설치 시에만 수행 (skip-if-not-installed).
"""
from __future__ import annotations

import numpy as np
import pytest

from gogoping_perception.pose_validator import (
    PoseResult,
    PoseValidator,
    count_visible_landmarks,
    is_bbox_too_small,
)


# ---------- pure functions ----------

def test_bbox_too_small_small():
    assert is_bbox_too_small((100, 100, 130, 140), min_side_px=40) is True


def test_bbox_too_small_large():
    assert is_bbox_too_small((100, 100, 200, 300), min_side_px=40) is False


def test_bbox_too_small_one_side_short():
    """한 변만 짧아도 True (skip)."""
    assert is_bbox_too_small((100, 100, 200, 130), min_side_px=40) is True


def test_count_visible_landmarks_none():
    assert count_visible_landmarks(None, visibility_threshold=0.5) == 0


def test_count_visible_landmarks_mixed():
    """mock landmark 객체로 visibility 점수 검증."""
    class _Lm:
        def __init__(self, v): self.visibility = v
    class _LmList:
        def __init__(self, vs): self.landmark = [_Lm(v) for v in vs]

    # visibility: [0.9, 0.4, 0.6, 0.2, 0.7]  → 0.5 이상 = 3개 (0.9, 0.6, 0.7)
    lms = _LmList([0.9, 0.4, 0.6, 0.2, 0.7])
    assert count_visible_landmarks(lms, visibility_threshold=0.5) == 3


def test_count_visible_landmarks_all_below():
    class _Lm:
        def __init__(self, v): self.visibility = v
    class _LmList:
        def __init__(self, vs): self.landmark = [_Lm(v) for v in vs]
    assert count_visible_landmarks(_LmList([0.1, 0.2, 0.3]), 0.5) == 0


# ---------- Validator (disabled / fallback) ----------

def test_validator_disabled_always_passes():
    """enabled=False 면 항상 is_person=True (안전 fallback)."""
    v = PoseValidator(
        enabled=False,
        min_visible_landmarks=5,
        visibility_threshold=0.5,
        min_bbox_side_px=40,
    )
    crop = np.zeros((100, 100, 3), dtype=np.uint8)
    res = v.validate(crop, (0, 0, 100, 100))
    assert res.is_person is True
    assert res.skipped_reason == "disabled"


def test_validator_too_small_passes():
    """bbox 너무 작으면 통과 (멀리 있는 사람 보호)."""
    v = PoseValidator(
        enabled=True,
        min_visible_landmarks=5,
        visibility_threshold=0.5,
        min_bbox_side_px=40,
    )
    crop = np.zeros((20, 30, 3), dtype=np.uint8)
    res = v.validate(crop, (0, 0, 30, 20))  # 한 변 20 < 40
    assert res.is_person is True
    assert res.skipped_reason == "too_small"


def test_validator_empty_crop_passes():
    """empty crop → 통과 (race condition 보호)."""
    v = PoseValidator(
        enabled=True,
        min_visible_landmarks=5,
        visibility_threshold=0.5,
        min_bbox_side_px=10,
    )
    crop = np.zeros((0, 0, 3), dtype=np.uint8)
    res = v.validate(crop, (0, 0, 100, 100))
    assert res.is_person is True


# ---------- Real MediaPipe inference (옵셔널 — installed 시) ----------

try:
    import mediapipe  # noqa: F401
    HAS_MEDIAPIPE = True
except ImportError:
    HAS_MEDIAPIPE = False


@pytest.mark.skipif(not HAS_MEDIAPIPE, reason="mediapipe not installed")
def test_validator_blank_image_no_person():
    """완전 검정 이미지 → keypoint 없음 → is_person=False (사물처럼)."""
    v = PoseValidator(
        enabled=True,
        min_visible_landmarks=5,
        visibility_threshold=0.5,
        min_bbox_side_px=40,
    )
    try:
        crop = np.zeros((200, 150, 3), dtype=np.uint8)  # 검정
        res = v.validate(crop, (0, 0, 150, 200))
        assert res.is_person is False
        assert res.n_visible < 5
    finally:
        v.close()


@pytest.mark.skipif(not HAS_MEDIAPIPE, reason="mediapipe not installed")
def test_validator_noise_image_no_person():
    """랜덤 노이즈 이미지 → keypoint 없거나 적음 → 사물 판정."""
    rng = np.random.default_rng(42)
    v = PoseValidator(
        enabled=True,
        min_visible_landmarks=5,
        visibility_threshold=0.5,
        min_bbox_side_px=40,
    )
    try:
        crop = rng.integers(0, 255, (200, 150, 3), dtype=np.uint8)
        res = v.validate(crop, (0, 0, 150, 200))
        # 노이즈는 거의 100% 사람 아님 판정
        assert res.is_person is False
    finally:
        v.close()
