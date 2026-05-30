"""mugunghwa_motion 순수 로직 테스트 — colcon build 없이 source 를 path 에 얹어 import."""
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]  # .../src/eduarm
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

import numpy as np  # noqa: E402

from eduarm.mugunghwa_motion import (  # noqa: E402
    bbox_motion,
    centroid,
    match_recognize_to_tracks,
    max_displacement,
    max_motion,
    select_movers,
    select_movers_sad,
)


def test_centroid():
    assert centroid((0, 0, 10, 20)) == (5.0, 10.0)


def test_match_recognize_greedy_iou():
    matches = [
        {"child_id": 7, "bbox": [10, 10, 50, 50]},
        {"child_id": 9, "bbox": [100, 100, 140, 140]},
    ]
    tracks = [
        {"track_id": 1, "bbox": (12, 12, 52, 52)},
        {"track_id": 2, "bbox": (98, 98, 138, 138)},
    ]
    assert match_recognize_to_tracks(matches, tracks) == {1: 7, 2: 9}


def test_match_recognize_no_overlap_unbound():
    matches = [{"child_id": 7, "bbox": [10, 10, 50, 50]}]
    tracks = [{"track_id": 1, "bbox": (200, 200, 240, 240)}]
    assert match_recognize_to_tracks(matches, tracks) == {}


def test_match_recognize_face_inside_person_binds():
    # recognize 는 InsightFace 얼굴 bbox(작음), track 은 YOLO 사람(class 0) bbox(큼).
    # 얼굴이 사람 박스 안에 들어가면 바인딩돼야 한다. IoU 로는 얼굴/사람 면적 차로 실패.
    matches = [{"child_id": 7, "bbox": [110, 100, 140, 150]}]   # 얼굴 30x50
    tracks = [{"track_id": 3, "bbox": (90, 90, 180, 400)}]      # 사람 90x310 (얼굴 포함)
    assert match_recognize_to_tracks(matches, tracks) == {3: 7}


def test_select_movers_strict():
    tracks = [
        {"track_id": 1, "bbox": (10, 10, 50, 50)},     # centroid (30,30)
        {"track_id": 2, "bbox": (100, 100, 140, 140)}, # centroid (120,120)
    ]
    baseline = {1: (30, 30), 2: (100, 100)}  # track2 변위 ≈28.3px
    bindings = {1: 7, 2: 9}
    assert select_movers(tracks, baseline, bindings, strict_px=10) == [9]


def test_select_movers_below_strict_none():
    # loose fallback 제거 — strict 미만이면 아무도 탈락 안 함(과민 방지).
    tracks = [
        {"track_id": 1, "bbox": (10, 10, 50, 50)},     # centroid (30,30)
        {"track_id": 2, "bbox": (100, 100, 140, 140)}, # centroid (120,120)
    ]
    baseline = {1: (29, 30), 2: (115, 120)}  # t1 dist=1, t2 dist=5 → 둘 다 strict(10) 미만
    bindings = {1: 7, 2: 9}
    assert select_movers(tracks, baseline, bindings, strict_px=10) == []


def test_select_movers_all_above_strict():
    tracks = [
        {"track_id": 1, "bbox": (10, 10, 50, 50)},     # (30,30)
        {"track_id": 2, "bbox": (100, 100, 140, 140)}, # (120,120)
    ]
    baseline = {1: (10, 30), 2: (100, 100)}  # t1 dist=20, t2 dist≈28 → 둘 다 strict 초과
    bindings = {1: 7, 2: 9}
    assert sorted(select_movers(tracks, baseline, bindings, strict_px=10)) == [7, 9]


def test_max_displacement_includes_unbound():
    tracks = [{"track_id": 5, "bbox": (10, 10, 50, 50)}]  # centroid (30,30)
    baseline = {5: (30, 24)}  # dist=6
    assert max_displacement(tracks, baseline) == 6.0


# ---- SAD(프레임 차분) 모션 ----------------------------------------------------

def test_bbox_motion_zero_when_identical():
    g = np.full((100, 100), 128, dtype=np.uint8)
    assert bbox_motion(g, g, (10, 10, 90, 90)) == 0.0


def test_bbox_motion_detects_local_change():
    # 몸 정지 + 팔만 흔들기 모사: bbox 의 일부 영역만 크게 변함 → 비율 > 0.
    prev = np.full((100, 100), 50, dtype=np.uint8)
    cur = prev.copy()
    cur[20:40, 20:30] = 200  # 국소 변화 (팔)
    m = bbox_motion(prev, cur, (0, 0, 100, 100), delta=25)
    assert m > 0.0
    # 변화 영역 = 20*10=200 / 10000 = 0.02
    assert abs(m - 0.02) < 1e-6


def test_bbox_motion_shape_mismatch_zero():
    a = np.zeros((10, 10), dtype=np.uint8)
    b = np.zeros((20, 20), dtype=np.uint8)
    assert bbox_motion(a, b, (0, 0, 10, 10)) == 0.0


def test_bbox_motion_ignore_mask_excludes_arm():
    # 변화 전체가 팔 영역(ignore_mask)에 있으면 → 0. 팔이 움직여도 탈락 안 남.
    prev = np.full((100, 100), 50, dtype=np.uint8)
    cur = prev.copy()
    cur[20:40, 20:30] = 200  # 변화 영역
    ignore = np.zeros((100, 100), dtype=bool)
    ignore[20:40, 20:30] = True  # 그 영역이 곧 로봇 팔
    assert bbox_motion(prev, cur, (0, 0, 100, 100), ignore_mask=ignore) == 0.0
    # 마스크 없으면 검출됨
    assert bbox_motion(prev, cur, (0, 0, 100, 100)) > 0.0


def test_select_movers_sad_strict_all():
    motion = {1: 0.05, 2: 0.06, 3: 0.001}
    bindings = {1: 7, 2: 8, 3: 9}
    assert sorted(select_movers_sad(motion, bindings, strict=0.03)) == [7, 8]


def test_select_movers_sad_below_strict_none():
    # loose fallback 제거 — strict 미만이면 탈락 없음(과민 방지). loose 는 flash 전용.
    motion = {1: 0.015, 2: 0.02}  # 둘 다 strict(0.03) 미만
    bindings = {1: 7, 2: 8}
    assert select_movers_sad(motion, bindings, strict=0.03) == []


def test_select_movers_sad_ignores_unbound():
    motion = {1: 0.05, 99: 0.05}  # 99 미바인딩
    bindings = {1: 7}
    assert select_movers_sad(motion, bindings, strict=0.03) == [7]


def test_max_motion():
    assert max_motion({1: 0.01, 2: 0.04}) == 0.04
    assert max_motion({}) == 0.0
