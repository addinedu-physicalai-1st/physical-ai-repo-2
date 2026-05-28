"""Camera pan/tilt P-control — pure logic, no ROS.

`compute_pan_target` / `compute_tilt_target` 는 한 tick 의 새 servo target 각도를
계산. step_limit 으로 부드러운 회전 보장.

부호 약속 (servo_bridge 의 회전 방향에 의존):
- pan : bbox 가 frame 오른쪽 (cx 큰 쪽) → output 음수 (카메라가 오른쪽으로 회전).
- tilt: bbox 가 frame 아래 (cy 큰 쪽) → output 양수 (servo_bridge 가 tilt 부호 처리).
"""
from __future__ import annotations


def step_limit(current: float, target: float, limit: float) -> float:
    """한 tick 의 변화량을 ±limit 안으로 클램프."""
    delta = target - current
    if delta > limit:
        return current + limit
    if delta < -limit:
        return current - limit
    return target


def _clamp(value: float, lo: float, hi: float) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def compute_pan_target(
    bbox_cx_px: float,
    frame_w_px: int,
    current_pan_deg: float,
    dead_zone_px: float,
    p_gain: float,
    pan_min: float,
    pan_max: float,
    step_limit_deg: float,
) -> float:
    cx_center = frame_w_px / 2.0
    offset_px = bbox_cx_px - cx_center
    if abs(offset_px) <= dead_zone_px:
        return current_pan_deg
    # servo 좌표계: pan 증가 = 오른쪽 (5° 왼쪽 ~ 175° 오른쪽).
    # bbox 오른쪽 (offset>0) → pan 증가 (오른쪽 회전) → 사람 frame 중앙으로.
    raw_target = current_pan_deg + p_gain * offset_px
    stepped = step_limit(current_pan_deg, raw_target, step_limit_deg)
    return _clamp(stepped, pan_min, pan_max)


def compute_tilt_target(
    bbox_cy_px: float,
    frame_h_px: int,
    current_tilt_deg: float,
    dead_zone_px: float,
    p_gain: float,
    tilt_min: float,
    tilt_max: float,
    step_limit_deg: float,
) -> float:
    cy_center = frame_h_px / 2.0
    offset_px = bbox_cy_px - cy_center
    if abs(offset_px) <= dead_zone_px:
        return current_tilt_deg
    # servo 좌표계: tilt 증가 = 위쪽 (100° home, 30° 아래 ~ 150° 위).
    # bbox 아래 (offset>0) → tilt 감소 (아래로) → 사람 frame 중앙으로.
    raw_target = current_tilt_deg - p_gain * offset_px
    stepped = step_limit(current_tilt_deg, raw_target, step_limit_deg)
    return _clamp(stepped, tilt_min, tilt_max)


def home_targets(pan_home: float, tilt_home: float) -> tuple[float, float]:
    return (pan_home, tilt_home)
