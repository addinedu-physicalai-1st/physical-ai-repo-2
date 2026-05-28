"""mugunghwa_motion 순수 로직 테스트 — colcon build 없이 source 를 path 에 얹어 import."""
import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]  # .../src/eduarm
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from eduarm.mugunghwa_motion import (  # noqa: E402
    centroid,
    match_recognize_to_tracks,
    max_displacement,
    select_movers,
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


def test_select_movers_strict():
    tracks = [
        {"track_id": 1, "bbox": (10, 10, 50, 50)},     # centroid (30,30)
        {"track_id": 2, "bbox": (100, 100, 140, 140)}, # centroid (120,120)
    ]
    baseline = {1: (30, 30), 2: (100, 100)}  # track2 변위 ≈28.3px
    bindings = {1: 7, 2: 9}
    assert select_movers(tracks, baseline, bindings, strict_px=10, loose_px=4) == [9]


def test_select_movers_loose_single_max():
    tracks = [
        {"track_id": 1, "bbox": (10, 10, 50, 50)},     # centroid (30,30)
        {"track_id": 2, "bbox": (100, 100, 140, 140)}, # centroid (120,120)
    ]
    baseline = {1: (29, 30), 2: (115, 120)}  # t1 dist=1, t2 dist=5 → 둘 다 strict 미만
    bindings = {1: 7, 2: 9}
    assert select_movers(tracks, baseline, bindings, strict_px=10, loose_px=4) == [9]


def test_select_movers_none_below_loose():
    tracks = [{"track_id": 1, "bbox": (10, 10, 50, 50)}]
    baseline = {1: (29, 30)}  # dist=1
    bindings = {1: 7}
    assert select_movers(tracks, baseline, bindings, strict_px=10, loose_px=4) == []


def test_max_displacement_includes_unbound():
    tracks = [{"track_id": 5, "bbox": (10, 10, 50, 50)}]  # centroid (30,30)
    baseline = {5: (30, 24)}  # dist=6
    assert max_displacement(tracks, baseline) == 6.0
