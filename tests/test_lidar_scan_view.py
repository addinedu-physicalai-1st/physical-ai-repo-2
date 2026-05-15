"""LidarScanView 스모크 — paintEvent 가 set_scan/set_meta 후 예외 없이 통과."""

from __future__ import annotations

import math
import os
import pytest


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _render(widget) -> None:
    """paintEvent 가 호출되도록 강제 — exception 안 나면 통과."""
    widget.resize(400, 400)
    widget.show()
    widget.repaint()


def test_lidar_scan_view_renders_empty(qt_app):
    from widgets.lidar_scan_view import LidarScanView
    w = LidarScanView()
    _render(w)


def test_lidar_scan_view_renders_with_data(qt_app):
    from widgets.lidar_scan_view import LidarScanView
    w = LidarScanView()
    w.set_scan(
        angle_min=-math.pi,
        angle_inc=2.0 * math.pi / 360.0,
        ranges=[2.0] * 360,
    )
    w.set_meta(hz=12.3, age_ms=84)
    _render(w)


def test_lidar_scan_view_renders_stale(qt_app):
    """age_ms > 500 분기 (신호 지연) 도 예외 없이."""
    from widgets.lidar_scan_view import LidarScanView
    w = LidarScanView()
    w.set_scan(
        angle_min=-math.pi,
        angle_inc=2.0 * math.pi / 360.0,
        ranges=[2.0] * 360,
    )
    w.set_meta(hz=12.3, age_ms=900)
    _render(w)


def test_lidar_scan_view_handles_inf(qt_app):
    """모두 inf 인 ranges 도 paint 예외 없음."""
    from widgets.lidar_scan_view import LidarScanView
    w = LidarScanView()
    w.set_scan(
        angle_min=-math.pi,
        angle_inc=2.0 * math.pi / 360.0,
        ranges=[float("inf")] * 360,
    )
    w.set_meta(hz=12.3, age_ms=84)
    _render(w)
