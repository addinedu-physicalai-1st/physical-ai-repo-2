"""Moca-style reactive P-control: distance + bearing → cmd_vel.

Pure Python — no rclpy. Called by `follow_node` in REACTIVE mode.

Sign conventions (matches perception_node output):
- angle_deg > 0  = 사람이 frame 왼쪽 → robot 좌회전 (angular.z > 0, CCW)
- distance_m > target_distance_m → robot 전진 (linear.x > 0)
- distance_m < target_distance_m → linear.x = 0 (후진 안 함, 안전상)
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ReactiveCmd:
    linear_x: float    # m/s, ≥ 0
    angular_z: float   # rad/s


def compute_reactive_cmd(
    distance_m: float,
    angle_deg: float,
    target_distance_m: float,
    kp_lin: float,
    kp_ang: float,
    max_lin: float,
    max_ang: float,
    dist_deadband_m: float,
    angle_deadband_deg: float,
) -> ReactiveCmd:
    """Distance + bearing → cmd_vel via simple P-control + deadband + clamp."""
    # 1) distance error → linear velocity (only forward).
    err_dist = distance_m - target_distance_m
    if abs(err_dist) < dist_deadband_m:
        linear_x = 0.0
    else:
        linear_x = kp_lin * err_dist
        # 후진 차단: 사람이 너무 가까우면 robot 정지 (STOP 모드가 별도 처리하지만
        # REACTIVE 진입 직후 buffer 로 한 번 더 안전망).
        if linear_x < 0.0:
            linear_x = 0.0
        # 상한 clamp
        if linear_x > max_lin:
            linear_x = max_lin

    # 2) angle error → angular velocity.
    if abs(angle_deg) < angle_deadband_deg:
        angular_z = 0.0
    else:
        err_angle_rad = math.radians(angle_deg)
        angular_z = kp_ang * err_angle_rad
        # 양/음 양쪽 clamp
        if angular_z > max_ang:
            angular_z = max_ang
        elif angular_z < -max_ang:
            angular_z = -max_ang

    return ReactiveCmd(linear_x=linear_x, angular_z=angular_z)
