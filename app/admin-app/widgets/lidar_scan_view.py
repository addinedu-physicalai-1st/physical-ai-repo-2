"""LiDAR 풀사이즈 뷰 — 폴라 플롯 + 헤더 + 십자 4방향 통계.

좌표 변환은 widgets.lidar_scan_math.polar_to_screen — ROS REP 103 → Qt top-down.
4방향 빈 평균은 widgets.lidar_scan_math.bin_directions.
"""

from __future__ import annotations

import math
from typing import Optional

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt5.QtWidgets import (
    QGridLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from theme import COLORS
from widgets.lidar_scan_math import bin_directions, polar_to_screen


MAX_RANGE_M = 5.0
RANGE_RINGS_M = (1.0, 2.0, 3.0, 4.0, 5.0)
FOV_HALF_DEG = 30.0
DIR_HALF_DEG = 15.0
STALE_MS = 500


def _lerp_color(c1: QColor, c2: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * t),
        int(c1.green() + (c2.green() - c1.green()) * t),
        int(c1.blue() + (c2.blue() - c1.blue()) * t),
    )


class _StatBox(QWidget):
    """앞/뒤/좌/우 거리 한 칸."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._value: Optional[float] = None
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def set_value(self, v: Optional[float]) -> None:
        self._value = v
        self.update()

    def paintEvent(self, _evt) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        p.fillPath(path, QColor(COLORS["bg_alt"]))
        p.setPen(QPen(QColor(COLORS["border"]), 1))
        p.drawPath(path)

        f = QFont(self.font())
        f.setPointSize(8)
        f.setBold(True)
        f.setLetterSpacing(QFont.PercentageSpacing, 110)
        p.setFont(f)
        p.setPen(QColor(COLORS["text_muted"]))
        p.drawText(rect.adjusted(8, 4, -8, -rect.height() / 2 + 2),
                   Qt.AlignLeft | Qt.AlignTop, self._label)

        f.setPointSize(14)
        f.setBold(True)
        f.setLetterSpacing(QFont.PercentageSpacing, 100)
        p.setFont(f)
        if self._value is None:
            p.setPen(QColor(COLORS["text_muted"]))
            text = "—"
        elif self._value < 1.0:
            p.setPen(QColor(COLORS["danger"]))
            text = f"{self._value:.2f} m"
        else:
            p.setPen(QColor(COLORS["text"]))
            text = f"{self._value:.2f} m"
        p.drawText(rect.adjusted(8, 0, -8, -4),
                   Qt.AlignRight | Qt.AlignBottom, text)


class _PolarPlot(QWidget):
    """폴라 플롯 본체 — paintEvent 만 담당."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # ⚠ minimumSize 는 카드 가용 height 보다 작아야 함. 너무 크게 강제하면 widget
        # logical rect 가 가용 영역 초과 → painter 가 visible 영역 밖에 그려 원이 잘림.
        # 잘림 방지 = 카드 height 안 polar 가용 영역과 호환되는 작은 minimum.
        self.setMinimumSize(160, 160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._angle_min = 0.0
        self._angle_inc = 0.0
        self._ranges: list[float] = []
        self._yaw = 0.0

    def set_scan(self, angle_min: float, angle_inc: float,
                 ranges: list[float]) -> None:
        self._angle_min = angle_min
        self._angle_inc = angle_inc
        self._ranges = list(ranges)
        self.update()

    def set_yaw(self, yaw: float) -> None:
        self._yaw = yaw
        self.update()

    def paintEvent(self, _evt) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)

        cx, cy = rect.center().x(), rect.center().y()
        radius = min(rect.width(), rect.height()) / 2 - 16
        bg = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg.setColorAt(0, QColor(COLORS["panel"]))
        bg.setColorAt(1, QColor(COLORS["bg_alt"]))
        path = QPainterPath()
        path.addEllipse(QPointF(cx, cy), radius + 4, radius + 4)
        p.fillPath(path, bg)
        p.setPen(QPen(QColor(COLORS["border_strong"]), 1.2))
        p.drawPath(path)

        # FOV cone (전방 ±30°) — mint
        cone = QColor(COLORS["mint"])
        cone.setAlpha(70)
        p.setBrush(cone)
        p.setPen(Qt.NoPen)
        cone_path = QPainterPath()
        cone_path.moveTo(cx, cy)
        rad = math.radians(FOV_HALF_DEG)
        for theta in (-rad, rad):
            ex, ey = polar_to_screen(
                theta=theta, r=MAX_RANGE_M, max_r=MAX_RANGE_M,
                radius=radius, cx=cx, cy=cy,
            )
            cone_path.lineTo(ex, ey)
        cone_path.closeSubpath()
        p.drawPath(cone_path)

        # range rings
        p.setPen(QPen(QColor(COLORS["border"]), 1, Qt.DotLine))
        for ring in RANGE_RINGS_M:
            rr = radius * ring / MAX_RANGE_M
            p.drawEllipse(QPointF(cx, cy), rr, rr)
        p.setPen(QPen(QColor(COLORS["border"]), 1))
        p.drawLine(QPointF(cx - radius, cy), QPointF(cx + radius, cy))
        p.drawLine(QPointF(cx, cy - radius), QPointF(cx, cy + radius))

        # 방위 라벨
        f = QFont(self.font())
        f.setPointSize(9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(COLORS["text_muted"]))
        p.drawText(QRectF(cx - 30, cy - radius - 18, 60, 14),
                   Qt.AlignHCenter, "앞")
        p.drawText(QRectF(cx - 30, cy + radius + 4, 60, 14),
                   Qt.AlignHCenter, "뒤")
        p.drawText(QRectF(cx - radius - 28, cy - 7, 24, 14),
                   Qt.AlignRight, "좌")
        p.drawText(QRectF(cx + radius + 4, cy - 7, 24, 14),
                   Qt.AlignLeft, "우")

        if not self._ranges:
            f.setPointSize(11)
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor(COLORS["text_muted"]))
            p.drawText(rect, Qt.AlignCenter, "데이터 없음")
            return

        # 점들 — 거리별 색조
        near = QColor(COLORS["danger"])
        far = QColor(COLORS["sky"])
        any_valid = False
        for i, r in enumerate(self._ranges):
            if not math.isfinite(r) or r <= 0:
                continue
            any_valid = True
            theta = self._angle_min + i * self._angle_inc
            t = min(r / MAX_RANGE_M, 1.0)
            col = _lerp_color(near, far, t)
            col.setAlpha(220)
            p.setPen(QPen(col, 2.4))
            px, py = polar_to_screen(
                theta=theta, r=r, max_r=MAX_RANGE_M,
                radius=radius, cx=cx, cy=cy,
            )
            p.drawPoint(QPointF(px, py))

        if not any_valid:
            f.setPointSize(11)
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor(COLORS["text_muted"]))
            p.drawText(rect, Qt.AlignCenter, "유효 점 없음")

        # 로봇 마커 + yaw 화살표
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(COLORS["primary"]))
        p.drawEllipse(QPointF(cx, cy), 5, 5)
        ax = cx - math.sin(self._yaw) * 14
        ay = cy - math.cos(self._yaw) * 14
        p.setPen(QPen(QColor(COLORS["primary"]), 2))
        p.drawLine(QPointF(cx, cy), QPointF(ax, ay))


class LidarScanView(QWidget):
    """LiDAR 분면 전체 — 헤더 + 십자 4방향 통계 + 폴라."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("lidarScanView")
        self._angle_min = 0.0
        self._angle_inc = 0.0
        self._ranges: list[float] = []
        self._hz = 0.0
        self._age_ms = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        self.header = QLabel("LiDAR · 0.0 Hz · 0 pts · age — ms")
        self.header.setObjectName("lidarHeader")
        self.header.setStyleSheet(
            f"color: {COLORS['lavender']}; font-size: 11pt; font-weight: 700;"
        )
        outer.addWidget(self.header)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        self.box_front = _StatBox("앞 ±15°")
        self.box_left = _StatBox("좌 ±15°")
        self.box_right = _StatBox("우 ±15°")
        self.box_back = _StatBox("뒤 ±15°")
        self.polar = _PolarPlot(self)

        grid.addWidget(self.box_front, 0, 1)
        grid.addWidget(self.box_left, 1, 0)
        grid.addWidget(self.polar, 1, 1)
        grid.addWidget(self.box_right, 1, 2)
        grid.addWidget(self.box_back, 2, 1)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setRowStretch(0, 0)
        grid.setRowStretch(1, 1)
        grid.setRowStretch(2, 0)
        # col 0/2 (좌·우 stat box) min 폭 축소 — polar 가 정사각형으로 차지할 공간 확보.
        # 이전 96/96 이면 우측 컬럼 폭 ~350 에서 polar 가로폭이 ~100 으로 압축돼 원이 작음.
        grid.setColumnMinimumWidth(0, 60)
        grid.setColumnMinimumWidth(2, 60)

        outer.addLayout(grid, 1)

    def set_scan(self, angle_min: float, angle_inc: float,
                 ranges: list[float]) -> None:
        self._angle_min = angle_min
        self._angle_inc = angle_inc
        self._ranges = list(ranges)
        self.polar.set_scan(angle_min, angle_inc, ranges)
        dirs = bin_directions(
            self._ranges, angle_min=angle_min, angle_inc=angle_inc,
            half_width_deg=DIR_HALF_DEG,
        )
        self.box_front.set_value(dirs["front"])
        self.box_back.set_value(dirs["back"])
        self.box_left.set_value(dirs["left"])
        self.box_right.set_value(dirs["right"])
        self._update_header()

    def set_meta(self, hz: float, age_ms: int) -> None:
        self._hz = hz
        self._age_ms = age_ms
        self._update_header()

    def set_yaw(self, yaw: float) -> None:
        self.polar.set_yaw(yaw)

    def _update_header(self) -> None:
        stale = self._age_ms > STALE_MS
        n_pts = len(self._ranges)
        age_text = f"{self._age_ms} ms" if n_pts else "—"
        text = f"LiDAR · {self._hz:.1f} Hz · {n_pts} pts · age {age_text}"
        if stale and n_pts:
            text += "  ⚠ 신호 지연"
        color = COLORS["danger"] if stale else COLORS["lavender"]
        self.header.setStyleSheet(
            f"color: {color}; font-size: 11pt; font-weight: 700;"
        )
        self.header.setText(text)
