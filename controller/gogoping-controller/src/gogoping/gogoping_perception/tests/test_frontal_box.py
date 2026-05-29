"""정면 박스 안 가장 가까운 사람 거리 계산 — pure logic."""
from math import inf

import numpy as np

from gogoping_perception.frontal_box import nearest_person_in_box


def test_no_detections_returns_inf():
    depth = np.zeros((480, 640), dtype=np.uint16)
    result = nearest_person_in_box(
        detections=[], depth=depth,
        fx=615.0, cx=320.0,
        box_forward_m=1.5, box_lateral_m=0.5,
    )
    assert result == inf


def test_person_centered_at_1m_returns_1m():
    depth = np.full((480, 640), 1000, dtype=np.uint16)
    detections = [(310, 200, 330, 400)]
    result = nearest_person_in_box(
        detections=detections, depth=depth,
        fx=615.0, cx=320.0,
        box_forward_m=1.5, box_lateral_m=0.5,
    )
    assert abs(result - 1.0) < 0.01


def test_person_just_inside_lateral():
    """이미지 가장자리이지만 0.5m 이내."""
    depth = np.full((480, 640), 1000, dtype=np.uint16)
    detections = [(420, 200, 460, 400)]  # 중심 = 440
    # (440-320)/615 * 1.0 = 0.195m → 박스 안
    result = nearest_person_in_box(
        detections=detections, depth=depth,
        fx=615.0, cx=320.0,
        box_forward_m=1.5, box_lateral_m=0.5,
    )
    assert abs(result - 1.0) < 0.01


def test_person_outside_lateral_returns_inf():
    """이미지 한참 가장자리 — lateral 0.5m 넘음."""
    depth = np.full((480, 640), 1000, dtype=np.uint16)
    # bbox 중심 x_pixel = 630, depth 1m. lateral ≈ 0.504m → 박스 밖.
    detections = [(620, 200, 640, 400)]
    result = nearest_person_in_box(
        detections=detections, depth=depth,
        fx=615.0, cx=320.0,
        box_forward_m=1.5, box_lateral_m=0.5,
    )
    assert result == inf


def test_person_too_far_returns_inf():
    """depth > forward_box (1.5m) — 박스 밖."""
    depth = np.full((480, 640), 2000, dtype=np.uint16)
    detections = [(310, 200, 330, 400)]
    result = nearest_person_in_box(
        detections=detections, depth=depth,
        fx=615.0, cx=320.0,
        box_forward_m=1.5, box_lateral_m=0.5,
    )
    assert result == inf


def test_picks_nearest_when_multiple():
    """여러 사람 있을 때 가장 가까운 거리 반환."""
    depth = np.zeros((480, 640), dtype=np.uint16)
    depth[200:400, 300:340] = 1200
    depth[200:400, 100:140] = 800
    detections = [
        (300, 200, 340, 400),
        (100, 200, 140, 400),
    ]
    result = nearest_person_in_box(
        detections=detections, depth=depth,
        fx=615.0, cx=320.0,
        box_forward_m=1.5, box_lateral_m=0.5,
    )
    assert abs(result - 0.8) < 0.05


def test_zero_depth_skipped():
    """depth == 0 (invalid) bbox 는 skip."""
    depth = np.zeros((480, 640), dtype=np.uint16)
    detections = [(310, 200, 330, 400)]
    result = nearest_person_in_box(
        detections=detections, depth=depth,
        fx=615.0, cx=320.0,
        box_forward_m=1.5, box_lateral_m=0.5,
    )
    assert result == inf

