"""LiDAR 좌표 변환 / 4방향 빈 평균 순수함수 테스트.

PyQt 의존 없음 — 어떤 환경에서도 실행 가능.
"""

from __future__ import annotations

import math

from widgets.lidar_scan_math import (
    bin_directions,
    polar_to_screen,
)


def test_polar_to_screen_front_is_up():
    """θ=0 (전방) 은 화면 위쪽 — (cx, cy - r)."""
    px, py = polar_to_screen(theta=0.0, r=1.0, max_r=1.0, radius=100.0, cx=200.0, cy=200.0)
    assert math.isclose(px, 200.0, abs_tol=1e-6)
    assert math.isclose(py, 100.0, abs_tol=1e-6)


def test_polar_to_screen_left_is_left():
    """θ=π/2 (좌측, ROS) 은 화면 왼쪽 — (cx - r, cy)."""
    px, py = polar_to_screen(theta=math.pi / 2, r=1.0, max_r=1.0, radius=100.0, cx=200.0, cy=200.0)
    assert math.isclose(px, 100.0, abs_tol=1e-6)
    assert math.isclose(py, 200.0, abs_tol=1e-6)


def test_polar_to_screen_back_is_down():
    """θ=π (후방) 은 화면 아래 — (cx, cy + r)."""
    px, py = polar_to_screen(theta=math.pi, r=1.0, max_r=1.0, radius=100.0, cx=200.0, cy=200.0)
    assert math.isclose(px, 200.0, abs_tol=1e-6)
    assert math.isclose(py, 300.0, abs_tol=1e-6)


def test_polar_to_screen_right_is_right():
    """θ=-π/2 (우측) 은 화면 오른쪽 — (cx + r, cy)."""
    px, py = polar_to_screen(theta=-math.pi / 2, r=1.0, max_r=1.0, radius=100.0, cx=200.0, cy=200.0)
    assert math.isclose(px, 300.0, abs_tol=1e-6)
    assert math.isclose(py, 200.0, abs_tol=1e-6)


def test_polar_to_screen_clips_to_max_r():
    """r > max_r 이면 max_r 로 clip (가장자리 링에 그려짐)."""
    px, py = polar_to_screen(theta=0.0, r=10.0, max_r=5.0, radius=100.0, cx=0.0, cy=0.0)
    assert math.isclose(py, -100.0, abs_tol=1e-6)  # 가장자리 = -radius


def test_bin_directions_front_back_left_right():
    """4방향 ±15° 빈에 각 1개씩만 점을 두고 빈 평균이 그 값이 되는지."""
    angle_min = -math.pi
    inc = 2.0 * math.pi / 360.0
    ranges = [float("inf")] * 360
    def idx(theta):
        return int(round((theta - angle_min) / inc)) % 360
    ranges[idx(0.0)] = 0.84            # 앞
    ranges[idx(math.pi)] = 4.21        # 뒤
    ranges[idx(math.pi / 2)] = 3.34    # 좌
    ranges[idx(-math.pi / 2)] = 3.27   # 우

    result = bin_directions(ranges, angle_min=angle_min, angle_inc=inc, half_width_deg=15.0)
    assert math.isclose(result["front"], 0.84, abs_tol=0.01)
    assert math.isclose(result["back"], 4.21, abs_tol=0.01)
    assert math.isclose(result["left"], 3.34, abs_tol=0.01)
    assert math.isclose(result["right"], 3.27, abs_tol=0.01)


def test_bin_directions_ignores_invalid():
    """inf / 0 / 음수는 빈 평균에서 제외."""
    angle_min = -math.pi
    inc = 2.0 * math.pi / 360.0
    ranges = [float("inf")] * 360
    front_i = int(round((0.0 - angle_min) / inc)) % 360
    ranges[front_i] = 1.0
    ranges[(front_i + 1) % 360] = float("inf")
    ranges[(front_i + 2) % 360] = 0.0

    result = bin_directions(ranges, angle_min=angle_min, angle_inc=inc, half_width_deg=15.0)
    assert math.isclose(result["front"], 1.0, abs_tol=0.01)


def test_bin_directions_nan_when_all_invalid():
    """모든 점이 invalid 면 None 반환."""
    result = bin_directions(
        [float("inf")] * 360, angle_min=-math.pi, angle_inc=2 * math.pi / 360.0,
        half_width_deg=15.0,
    )
    assert result["front"] is None
    assert result["back"] is None
    assert result["left"] is None
    assert result["right"] is None
