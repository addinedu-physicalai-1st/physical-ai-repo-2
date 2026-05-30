"""팔 self-filter 순수 기하 테스트."""
import sys
from pathlib import Path

import numpy as np

_PKG = Path(__file__).resolve().parents[1]  # .../src/eduarm
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from eduarm.arm_self_mask import (  # noqa: E402
    arm_pixel_mask,
    backproject,
    _point_segment_distance,
)


def test_backproject_center_pixel():
    # cx,cy 중심 픽셀 + depth 1000mm → (0,0,1.0).
    d = np.full((1, 1), 1000, dtype=np.uint16)
    pts = backproject(d, x0=320, y0=240, fx=400, fy=400, cx=320, cy=240)
    assert pts.shape == (1, 1, 3)
    assert np.allclose(pts[0, 0], [0.0, 0.0, 1.0], atol=1e-5)


def test_backproject_offset_pixel():
    # cx 에서 +fx 픽셀 떨어진 점, depth 2000mm → X = (1)·Z = 2.0.
    d = np.full((1, 1), 2000, dtype=np.uint16)
    pts = backproject(d, x0=720, y0=240, fx=400, fy=400, cx=320, cy=240)
    # u = 720, (720-320)/400 = 1.0 → X = 1.0 * 2.0 = 2.0
    assert np.allclose(pts[0, 0], [2.0, 0.0, 2.0], atol=1e-4)


def test_backproject_invalid_stays_zero():
    d = np.zeros((1, 1), dtype=np.uint16)
    pts = backproject(d, 0, 0, 400, 400, 320, 240)
    assert pts[0, 0, 2] == 0.0


def test_point_segment_distance_perpendicular():
    pts = np.array([[0.0, 1.0, 0.0]])
    dist = _point_segment_distance(pts, np.array([-1.0, 0, 0]), np.array([1.0, 0, 0]))
    assert np.isclose(dist[0], 1.0)


def test_point_segment_distance_beyond_endpoint():
    # 선분 끝을 넘어선 점 → 끝점까지 거리.
    pts = np.array([[2.0, 0.0, 0.0]])
    dist = _point_segment_distance(pts, np.array([-1.0, 0, 0]), np.array([1.0, 0, 0]))
    assert np.isclose(dist[0], 1.0)


def test_arm_mask_within_capsule():
    pts = np.array([
        [0.0, 0.05, 1.0],   # 세그먼트(1m 거리)에서 5cm — 반경 0.08 안 → True
        [0.0, 0.5, 1.0],    # 50cm — 밖 → False
        [0.0, 0.0, 0.0],    # invalid → False
    ])
    seg = (np.array([-0.2, 0, 1.0]), np.array([0.2, 0, 1.0]), 0.08)
    mask = arm_pixel_mask(pts, [seg])
    assert mask.tolist() == [True, False, False]


def test_arm_mask_empty_segments():
    pts = np.array([[0.0, 0.0, 1.0]])
    assert arm_pixel_mask(pts, []).tolist() == [False]
