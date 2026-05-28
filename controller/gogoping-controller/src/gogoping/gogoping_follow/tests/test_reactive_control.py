"""Unit tests for reactive_control.compute_reactive_cmd (moca-style P-control)."""
import math

from gogoping_follow.reactive_control import compute_reactive_cmd, ReactiveCmd


# Reusable P-control args matching config.py defaults
P_ARGS = dict(
    target_distance_m=0.5,
    kp_lin=0.5,
    kp_ang=0.6,
    max_lin=0.3,
    max_ang=0.4,
    dist_deadband_m=0.05,
    angle_deadband_deg=5.0,
)


def test_at_settle_distance_and_centered_returns_zero():
    cmd = compute_reactive_cmd(distance_m=0.5, angle_deg=0.0, **P_ARGS)
    assert cmd.linear_x == 0.0
    assert cmd.angular_z == 0.0


def test_far_person_drives_forward():
    cmd = compute_reactive_cmd(distance_m=0.9, angle_deg=0.0, **P_ARGS)
    # err_dist = 0.4 > deadband 0.05 → linear = 0.5 * 0.4 = 0.2 (< max 0.3)
    assert cmd.linear_x == 0.2
    assert cmd.angular_z == 0.0


def test_close_person_does_not_reverse():
    # err_dist = -0.1 (음수, 너무 가까움). 후진 차단 → linear = 0
    cmd = compute_reactive_cmd(distance_m=0.4, angle_deg=0.0, **P_ARGS)
    assert cmd.linear_x == 0.0
    assert cmd.angular_z == 0.0


def test_person_on_left_turns_left():
    # angle_deg > 0 = 사람 왼쪽 (perception convention). robot 도 좌회전 = angular > 0.
    cmd = compute_reactive_cmd(distance_m=0.5, angle_deg=30.0, **P_ARGS)
    # err_angle_rad = 30° in rad = 0.5236. kp_ang * 0.5236 = 0.314 (< max 0.4)
    assert cmd.angular_z > 0
    assert cmd.angular_z == max(min(0.6 * math.radians(30.0), 0.4), -0.4)


def test_person_on_right_turns_right():
    cmd = compute_reactive_cmd(distance_m=0.5, angle_deg=-30.0, **P_ARGS)
    assert cmd.angular_z < 0


def test_angle_deadband_zero_small_angle():
    # |angle_deg| < deadband 5° → angular = 0
    cmd = compute_reactive_cmd(distance_m=0.5, angle_deg=3.0, **P_ARGS)
    assert cmd.angular_z == 0.0


def test_dist_deadband_zero_small_error():
    # |dist - target| < deadband 0.05 → linear = 0
    cmd = compute_reactive_cmd(distance_m=0.53, angle_deg=0.0, **P_ARGS)
    assert cmd.linear_x == 0.0


def test_linear_clamped_at_max():
    # err_dist 큰 값 → kp*err 가 max 초과 → max 로 clamp
    cmd = compute_reactive_cmd(distance_m=5.0, angle_deg=0.0, **P_ARGS)
    assert cmd.linear_x == 0.3  # max_lin


def test_angular_clamped_at_max_magnitude():
    cmd = compute_reactive_cmd(distance_m=0.5, angle_deg=180.0, **P_ARGS)
    assert cmd.angular_z == 0.4  # +max_ang


def test_angular_clamped_at_min_magnitude():
    cmd = compute_reactive_cmd(distance_m=0.5, angle_deg=-180.0, **P_ARGS)
    assert cmd.angular_z == -0.4  # -max_ang


def test_combined_far_and_off_center():
    # 둘 다 동시 동작
    cmd = compute_reactive_cmd(distance_m=0.8, angle_deg=20.0, **P_ARGS)
    assert cmd.linear_x > 0
    assert cmd.angular_z > 0


def test_returns_reactive_cmd_dataclass():
    cmd = compute_reactive_cmd(distance_m=0.5, angle_deg=0.0, **P_ARGS)
    assert isinstance(cmd, ReactiveCmd)
