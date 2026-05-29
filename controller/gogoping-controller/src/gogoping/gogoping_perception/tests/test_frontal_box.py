"""정면 박스 안 가장 가까운 사람 거리 계산 — pure logic."""
from math import inf

import numpy as np

from gogoping_perception.frontal_box import (
    nearest_in_box_split,
    nearest_obstacle_forward,
    nearest_person_in_box,
)

_OBS_KW = dict(
    depth_min_mm=200, depth_max_mm=8000,
    row_top_frac=0.30, row_bot_frac=0.60, col_half_frac=0.25,
    percentile=5.0,
)


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


# ── nearest_obstacle_forward (depth-only 정면 최근접 장애물) ──

def test_obstacle_empty_depth_returns_inf():
    assert nearest_obstacle_forward(np.zeros((480, 640), dtype=np.uint16), **_OBS_KW) == inf


def test_obstacle_uniform_returns_distance():
    """중앙 밴드 전체가 1.5m → 1.5m 반환."""
    depth = np.full((480, 640), 1500, dtype=np.uint16)
    result = nearest_obstacle_forward(depth, **_OBS_KW)
    assert abs(result - 1.5) < 0.01


def test_obstacle_ignores_floor_in_lower_rows():
    """하단(바닥) 0.4m, 중앙 밴드 2.0m → ROI 가 바닥 제외하므로 2.0m."""
    depth = np.full((480, 640), 2000, dtype=np.uint16)
    depth[400:480, :] = 400  # 영상 하단 = 바닥, 매우 가까움
    result = nearest_obstacle_forward(depth, **_OBS_KW)
    assert abs(result - 2.0) < 0.05


def test_obstacle_percentile_picks_near_cluster():
    """중앙 밴드에 가까운 물체(0.6m) 일부 + 배경(3.0m) → 저백분위가 가까운 값."""
    depth = np.full((480, 640), 3000, dtype=np.uint16)
    depth[150:280, 300:360] = 600  # ROI(행 144~288, 열 160~480) 안 일부
    result = nearest_obstacle_forward(depth, **_OBS_KW)
    assert result < 1.0


# ── nearest_in_box_split (중앙 ROI 사람/비-사람 분리 최근접) ──
# ROI: 행 144~288, 열 160~480 (_OBS_KW 기준).

def test_split_no_detections_all_obstacle():
    """detections 없으면 person=inf, obstacle 은 ROI 최근접(nearest_obstacle_forward 와 동일)."""
    depth = np.full((480, 640), 1500, dtype=np.uint16)
    person_m, obstacle_m = nearest_in_box_split(depth, [], **_OBS_KW)
    assert person_m == inf
    assert abs(obstacle_m - 1.5) < 0.01


def test_split_empty_depth_returns_inf_inf():
    """전부 invalid depth → (inf, inf)."""
    depth = np.zeros((480, 640), dtype=np.uint16)
    person_m, obstacle_m = nearest_in_box_split(
        depth, [(300, 200, 340, 400)], **_OBS_KW
    )
    assert person_m == inf
    assert obstacle_m == inf


def test_split_person_covers_near_cluster():
    """가까운 0.6m 덩어리가 사람 bbox 안 → person 으로 분류, obstacle 은 배경 3.0m."""
    depth = np.full((480, 640), 3000, dtype=np.uint16)
    depth[150:280, 300:360] = 600          # ROI 안 가까운 덩어리
    detections = [(290, 140, 370, 290)]    # 그 덩어리를 덮는 사람 bbox
    person_m, obstacle_m = nearest_in_box_split(depth, detections, **_OBS_KW)
    assert person_m < 1.0                  # 사람으로 잡힘
    assert abs(obstacle_m - 3.0) < 0.1     # 나머지는 배경


def test_split_obstacle_nearer_than_person():
    """비-사람 0.5m 물체 + 사람 2.0m → obstacle 가 person 보다 가까움."""
    depth = np.full((480, 640), 8000, dtype=np.uint16)
    depth[150:280, 170:230] = 500          # 비-사람 가까운 물체 (사람 bbox 밖)
    depth[150:280, 350:410] = 2000         # 사람 영역
    detections = [(340, 140, 420, 290)]
    person_m, obstacle_m = nearest_in_box_split(depth, detections, **_OBS_KW)
    assert abs(person_m - 2.0) < 0.1
    assert obstacle_m < 1.0
    assert obstacle_m < person_m
