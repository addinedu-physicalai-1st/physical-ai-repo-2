"""safety_monitor pure-logic unit tests."""
import numpy as np
import pytest

from gogoping_perception.safety_monitor import (
    evaluate_safety,
    SafetyDecision,
    SafetyEvalContext,
)
from gogoping_perception import config


def _depth(height: int = 480, width: int = 640, fill_mm: int = 3000) -> np.ndarray:
    return np.full((height, width), fill_mm, dtype=np.uint16)


def test_no_state_no_distance_no_obstacle_returns_false():
    ctx = SafetyEvalContext(
        depth=_depth(),
        tracking_distance_mm=2000,
        tracking_bbox=None,
        current_state="ASSIST",
    )
    d = evaluate_safety(ctx)
    assert d.stop is False
    assert d.reason == "ok"


def test_distance_below_floor_triggers_stop():
    # SAFE_DISTANCE_MM = 300 (hybrid follow STOP_MAX_CLOSE_M=0.25 와 정합).
    # 200mm < 300 → person_close stop trigger.
    ctx = SafetyEvalContext(
        depth=_depth(),
        tracking_distance_mm=200,
        tracking_bbox=None,
        current_state="ASSIST",
    )
    d = evaluate_safety(ctx)
    assert d.stop is True
    assert d.reason == "person_close"


def test_distance_zero_means_invalid_not_close():
    """distance_mm = 0 은 invalid (perception 의 default) — close 으로 오인 X."""
    ctx = SafetyEvalContext(
        depth=_depth(),
        tracking_distance_mm=0,
        tracking_bbox=None,
        current_state="ASSIST",
    )
    d = evaluate_safety(ctx)
    assert d.stop is False


def test_obstacle_in_lower_roi_triggers_stop():
    """화면 하단 60% 영역의 < 500mm pixel 1000+ 면 stop."""
    h, w = 480, 640
    depth = _depth(h, w, fill_mm=3000)
    depth[300:400, 200:220] = 400   # 2000 pixel
    ctx = SafetyEvalContext(
        depth=depth,
        tracking_distance_mm=2000,
        tracking_bbox=None,
        current_state="ASSIST",
    )
    d = evaluate_safety(ctx)
    assert d.stop is True
    assert d.reason == "obstacle"


def test_obstacle_in_upper_roi_ignored():
    """화면 위 40% (천장/벽) 의 < 500mm pixel 은 무시."""
    h, w = 480, 640
    depth = _depth(h, w, fill_mm=3000)
    depth[10:100, 10:200] = 400
    ctx = SafetyEvalContext(
        depth=depth,
        tracking_distance_mm=2000,
        tracking_bbox=None,
        current_state="ASSIST",
    )
    d = evaluate_safety(ctx)
    assert d.stop is False


def test_bbox_pixels_excluded_from_obstacle():
    """tracking.bbox 영역의 pixel 은 obstacle 판정에서 제외."""
    h, w = 480, 640
    depth = _depth(h, w, fill_mm=3000)
    depth[300:400, 200:300] = 400   # bbox 안 pixel
    ctx = SafetyEvalContext(
        depth=depth,
        tracking_distance_mm=2000,
        tracking_bbox=(200, 300, 300, 400),
        current_state="ASSIST",
    )
    d = evaluate_safety(ctx)
    assert d.stop is False


def test_zero_depth_pixels_not_counted_as_obstacle():
    """depth = 0 (invalid) 은 close 으로 오인 X."""
    h, w = 480, 640
    depth = np.zeros((h, w), dtype=np.uint16)
    ctx = SafetyEvalContext(
        depth=depth,
        tracking_distance_mm=2000,
        tracking_bbox=None,
        current_state="ASSIST",
    )
    d = evaluate_safety(ctx)
    assert d.stop is False


def test_manual_state_bypasses_safety():
    """current_state=MANUAL 면 항상 stop=False."""
    h, w = 480, 640
    depth = _depth(h, w, fill_mm=3000)
    depth[300:400, 200:220] = 400
    ctx = SafetyEvalContext(
        depth=depth,
        tracking_distance_mm=500,
        tracking_bbox=None,
        current_state="MANUAL",
    )
    d = evaluate_safety(ctx)
    assert d.stop is False
    assert d.reason == "bypassed_manual"


# ---- evaluate_proximity_level tests (graph_router 심화) ----
from math import inf

from gogoping_perception import config
from gogoping_perception.safety_monitor import evaluate_proximity_level


def test_proximity_ok_no_person():
    assert evaluate_proximity_level(
        person_dist_m=inf, current_state="GOTO"
    ) == "ok"


def test_proximity_person_close():
    # 사람 임계 안 → person_close (person-only; 장애물 판정 제거됨).
    assert evaluate_proximity_level(
        person_dist_m=config.PERSON_FRONT_DIST_M - 0.1,
        current_state="GOTO",
    ) == "person_close"


def test_proximity_bypass_in_manual():
    assert evaluate_proximity_level(
        person_dist_m=0.5, current_state="MANUAL"
    ) == "ok"


def test_proximity_person_at_exact_threshold():
    # 정확히 임계값(<=) 이면 person_close.
    assert evaluate_proximity_level(
        person_dist_m=config.PERSON_FRONT_DIST_M, current_state="GOTO"
    ) == "person_close"
