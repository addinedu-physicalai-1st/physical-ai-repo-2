"""ODOM compact — Teleop 분면 아래 칸. compass dial + x/y/yaw 라벨."""

from __future__ import annotations

import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from theme import COLORS


class _Compass(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._yaw = 0.0
        self.setFixedSize(86, 86)

    def set_yaw(self, yaw: float) -> None:
        self._yaw = yaw
        self.update()

    def paintEvent(self, _evt) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        cx, cy = rect.center().x(), rect.center().y()
        r = min(rect.width(), rect.height()) / 2 - 2

        p.setBrush(QColor(COLORS["panel"]))
        p.setPen(QPen(QColor(COLORS["border_strong"]), 1.5))
        p.drawEllipse(QPointF(cx, cy), r, r)

        f = QFont(self.font())
        f.setPointSize(8)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(COLORS["text_muted"]))
        p.drawText(QRectF(cx - 10, cy - r + 1, 20, 12),
                   Qt.AlignHCenter, "N")

        # yaw 화살표 — yaw=0 이 위쪽 (전방). lidar_scan_view 의 컨벤션과 동일.
        ax = cx - math.sin(self._yaw) * (r - 8)
        ay = cy - math.cos(self._yaw) * (r - 8)
        p.setPen(QPen(QColor(COLORS["primary"]), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx, cy), QPointF(ax, ay))
        p.setBrush(QColor(COLORS["primary"]))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), 3, 3)


class OdomCompact(QWidget):
    """ODOM compact — compass + x/y/yaw."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("odomCompact")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # horizontal: [compass | (x / y / yaw 라벨 세로 스택)]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(12)

        self.compass = _Compass(self)
        lay.addWidget(self.compass, 0, Qt.AlignVCenter)

        label_col = QVBoxLayout()
        label_col.setContentsMargins(0, 0, 0, 0)
        label_col.setSpacing(2)
        self.x_label = QLabel("x +0.00")
        self.y_label = QLabel("y +0.00")
        self.yaw_label = QLabel("yaw +0°")
        for lab in (self.x_label, self.y_label, self.yaw_label):
            lab.setStyleSheet(
                f"color: {COLORS['text']}; font-size: 10pt; font-weight: 600;"
            )
            label_col.addWidget(lab)
        lay.addLayout(label_col, 1)

    def set_odom(self, x: float, y: float, yaw: float) -> None:
        self.compass.set_yaw(yaw)
        self.x_label.setText(f"x {x:+.2f}")
        self.y_label.setText(f"y {y:+.2f}")
        deg = math.degrees(yaw)
        self.yaw_label.setText(f"yaw {deg:+.0f}°")
