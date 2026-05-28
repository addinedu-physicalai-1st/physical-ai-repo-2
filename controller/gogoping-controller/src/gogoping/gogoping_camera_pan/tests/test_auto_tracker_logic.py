"""Camera pan/tilt P-control + step limiter — pure logic."""
import math

import pytest

from gogoping_camera_pan.auto_tracker_logic import (
    compute_pan_target,
    compute_tilt_target,
    home_targets,
    step_limit,
)


def test_pan_dead_zone() -> None:
    # bbox center_x 가 frame center (320) 의 ±30 안 → 변화 0
    out = compute_pan_target(
        bbox_cx_px=325, frame_w_px=640,
        current_pan_deg=10.0,
        dead_zone_px=30, p_gain=0.05,
        pan_min=-45.0, pan_max=45.0,
        step_limit_deg=5.0,
    )
    assert out == pytest.approx(10.0)


def test_pan_moves_right_for_right_bbox() -> None:
    """servo coord: pan+ = 오른쪽. bbox 오른쪽 (offset>0) → pan + (오른쪽 회전)."""
    out = compute_pan_target(
        bbox_cx_px=480, frame_w_px=640,
        current_pan_deg=0.0,
        dead_zone_px=30, p_gain=0.05,
        pan_min=-45.0, pan_max=45.0,
        step_limit_deg=5.0,
    )
    # offset = 480 - 320 = 160 → +160 * 0.05 = +8°. step_limit 5 → +5°.
    assert out == pytest.approx(5.0)


def test_pan_moves_left_for_left_bbox() -> None:
    out = compute_pan_target(
        bbox_cx_px=160, frame_w_px=640,
        current_pan_deg=0.0,
        dead_zone_px=30, p_gain=0.05,
        pan_min=-45.0, pan_max=45.0,
        step_limit_deg=5.0,
    )
    # offset = 160 - 320 = -160 → -160 * 0.05 = -8°. step_limit 5 → -5°.
    assert out == pytest.approx(-5.0)


def test_pan_step_limit() -> None:
    out = compute_pan_target(
        bbox_cx_px=640, frame_w_px=640,
        current_pan_deg=0.0,
        dead_zone_px=30, p_gain=0.05,
        pan_min=-45.0, pan_max=45.0,
        step_limit_deg=5.0,
    )
    # offset 320 → +16°. step_limit 5 → +5°.
    assert out == pytest.approx(5.0)


def test_pan_clamped_to_min_max() -> None:
    # current 가 이미 44° 인 상태에서 더 + 방향 step → 45° clamp
    out = compute_pan_target(
        bbox_cx_px=640, frame_w_px=640,
        current_pan_deg=44.0,
        dead_zone_px=30, p_gain=0.05,
        pan_min=-45.0, pan_max=45.0,
        step_limit_deg=5.0,
    )
    assert out == pytest.approx(45.0)


def test_tilt_moves_down_for_low_bbox() -> None:
    """servo coord: tilt+ = 위. bbox 아래 (cy > center, offset>0) → tilt - (아래로)."""
    out = compute_tilt_target(
        bbox_cy_px=400, frame_h_px=480,
        current_tilt_deg=0.0,
        dead_zone_px=30, p_gain=0.05,
        tilt_min=-20.0, tilt_max=30.0,
        step_limit_deg=5.0,
    )
    # offset = 400 - 240 = 160 → -160*0.05 = -8°. step_limit 5 → -5°.
    assert out == pytest.approx(-5.0)


def test_step_limit_helper() -> None:
    assert step_limit(0.0, 10.0, 5.0) == pytest.approx(5.0)
    assert step_limit(0.0, -10.0, 5.0) == pytest.approx(-5.0)
    assert step_limit(0.0, 3.0, 5.0) == pytest.approx(3.0)
    assert step_limit(10.0, 7.0, 5.0) == pytest.approx(7.0)


def test_home_targets() -> None:
    pan, tilt = home_targets(pan_home=0.0, tilt_home=0.0)
    assert pan == pytest.approx(0.0)
    assert tilt == pytest.approx(0.0)
