"""depth-aware mask unit tests — extract_with_mask."""
import numpy as np
import pytest

from gogoping_perception.reid_engine import ReIDEngine


def test_extract_with_mask_returns_array():
    """기본 호출 — masked region 의 emb 가 정상 shape 으로 나옴."""
    engine = ReIDEngine(device='cpu')
    # 60x40 BGR ROI — 좌상단 절반은 1500mm (사람), 우하단 절반은 5000mm (벽)
    crop = (np.ones((60, 40, 3), dtype=np.uint8) * 128)
    depth = np.zeros((60, 40), dtype=np.uint16)
    depth[:30, :] = 1500   # 사람 영역
    depth[30:, :] = 5000   # 벽
    feat = engine.extract_with_mask(crop, depth, target_distance_mm=1500, tolerance_mm=200)
    assert isinstance(feat, np.ndarray)
    assert feat.ndim == 1
    assert feat.shape[0] == engine.feat_dim


def test_extract_with_mask_falls_back_when_sparse():
    """valid pixel 비율 < 0.3 면 mask 안 씌우고 full bbox 사용."""
    engine = ReIDEngine(device='cpu')
    crop = (np.ones((60, 40, 3), dtype=np.uint8) * 128)
    # depth 가 거의 0 (invalid). target 과 매칭되는 pixel 거의 없음.
    depth = np.zeros((60, 40), dtype=np.uint16)
    # 5개 pixel 만 valid — valid_ratio = 5/(60*40) ≈ 0.002 << 0.3
    depth[0, 0] = 1500
    depth[0, 1] = 1500
    depth[0, 2] = 1500
    depth[0, 3] = 1500
    depth[0, 4] = 1500
    feat = engine.extract_with_mask(crop, depth, target_distance_mm=1500, tolerance_mm=200)
    # fallback: full bbox embedding 과 같음
    feat_full = engine.extract_features(crop)
    assert np.allclose(feat, feat_full, atol=1e-5)


def test_extract_with_mask_empty_inputs():
    """빈 입력 시 zero vector."""
    engine = ReIDEngine(device='cpu')
    empty_crop = np.zeros((0, 0, 3), dtype=np.uint8)
    empty_depth = np.zeros((0, 0), dtype=np.uint16)
    feat = engine.extract_with_mask(empty_crop, empty_depth, target_distance_mm=1500)
    assert feat.shape[0] == engine.feat_dim
    assert np.allclose(feat, 0.0)
