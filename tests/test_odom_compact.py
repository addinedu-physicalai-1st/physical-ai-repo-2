"""OdomCompact 스모크."""

from __future__ import annotations

import os
import pytest


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _render(w) -> None:
    w.resize(160, 200)
    w.show()
    w.repaint()


def test_odom_compact_renders_empty(qt_app):
    from widgets.odom_compact import OdomCompact
    w = OdomCompact()
    _render(w)


def test_odom_compact_renders_with_data(qt_app):
    from widgets.odom_compact import OdomCompact
    w = OdomCompact()
    w.set_odom(x=1.23, y=-0.45, yaw=0.61)  # ~35°
    _render(w)


def test_odom_compact_label_updates(qt_app):
    """set_odom 호출 후 내부 레이블 텍스트가 갱신되어야 함."""
    from widgets.odom_compact import OdomCompact
    w = OdomCompact()
    w.set_odom(x=2.0, y=3.0, yaw=0.0)
    assert "2.00" in w.x_label.text()
    assert "3.00" in w.y_label.text()
