"""RosBridge._on_scan Hz EMA 측정 단위 테스트.

rclpy 가 없는 환경에서도 동작해야 하므로 _on_scan 만 직접 호출한다.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from control_service.teleop.ros_bridge import RosBridge


def _fake_scan(ranges: list[float] | None = None):
    """LaserScan 흉내 — _on_scan 이 사용하는 필드만 채움."""
    return SimpleNamespace(
        angle_min=-3.14,
        angle_increment=0.01,
        ranges=ranges if ranges is not None else [1.0] * 360,
    )


def test_scan_hz_zero_on_first_callback():
    """첫 콜백에선 이전 timestamp 가 없으므로 hz=0.0."""
    b = RosBridge()
    with patch("time.monotonic", return_value=100.0):
        b._on_scan(_fake_scan())
    snap = b.snapshot()
    assert snap["scan"] is not None
    assert snap["scan"]["hz"] == 0.0


def test_scan_hz_converges_to_10_at_100ms_interval():
    """100ms 간격 5회 콜백 → hz ≈ 10 (EMA α=0.2)."""
    b = RosBridge()
    # 첫 호출 = 100.0s, 이후 0.1s 씩 증가
    ts = [100.0, 100.1, 100.2, 100.3, 100.4]
    for t in ts:
        with patch("time.monotonic", return_value=t):
            b._on_scan(_fake_scan())
    snap = b.snapshot()
    # 첫 콜백 후엔 0, 두 번째부터 EMA — 5회면 9~11Hz 수렴
    assert 9.0 <= snap["scan"]["hz"] <= 11.0


def test_scan_age_ms_increases_when_no_new_scan():
    """콜백 1회 후 monotonic 시간이 흘러도 age_ms 가 증가."""
    b = RosBridge()
    with patch("time.monotonic", return_value=100.0):
        b._on_scan(_fake_scan())
    # snapshot 시 monotonic 이 200ms 흐른 상태
    with patch("time.monotonic", return_value=100.2):
        snap = b.snapshot()
    assert snap["scan"]["age_ms"] >= 200


def test_scan_hz_ignores_sub_millisecond_dt():
    """dt < 1ms 인 콜백은 EMA 갱신에서 무시 — hz 0.0 유지."""
    b = RosBridge()
    with patch("time.monotonic", return_value=100.0):
        b._on_scan(_fake_scan())
    with patch("time.monotonic", return_value=100.0005):   # 0.5 ms 후
        b._on_scan(_fake_scan())
    snap = b.snapshot()
    assert snap["scan"]["hz"] == 0.0
