"""Admin UI 공용 위젯.

이모지 대신 QPainter 로 그린 벡터 아이콘을 사용한다 (`draw_icon`).
폰트/플랫폼별 이모지 렌더링 차이에 영향을 받지 않는다.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from theme import COLORS


# --------------------------------------------------------------------------
# 아이콘 시스템
# --------------------------------------------------------------------------


def _P(rect: QRectF, x: float, y: float) -> QPointF:
    """[0,1]^2 좌표를 rect 안의 QPointF 로 변환."""
    return QPointF(rect.x() + rect.width() * x, rect.y() + rect.height() * y)


def draw_icon(p: QPainter, kind: str, rect: QRectF, color: str,
              line_ratio: float = 0.10) -> None:
    """rect 안에 kind 종류의 벡터 아이콘을 그린다."""
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    qcol = QColor(color)
    s = min(rect.width(), rect.height())

    sub = QRectF(
        rect.center().x() - s * 0.45,
        rect.center().y() - s * 0.45,
        s * 0.90,
        s * 0.90,
    )
    lw = max(1.4, s * line_ratio)
    pen = QPen(qcol, lw)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    PT = lambda x, y: _P(sub, x, y)

    if kind == "arm":
        path = QPainterPath()
        path.moveTo(PT(0.22, 0.88))
        path.lineTo(PT(0.22, 0.52))
        path.lineTo(PT(0.55, 0.32))
        path.lineTo(PT(0.82, 0.46))
        p.drawPath(path)
        p.drawLine(PT(0.78, 0.40), PT(0.92, 0.30))
        p.drawLine(PT(0.78, 0.52), PT(0.92, 0.58))
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        p.drawEllipse(PT(0.22, 0.88), s * 0.06, s * 0.06)

    elif kind == "vehicle":
        body = QRectF(PT(0.10, 0.32).x(), PT(0.10, 0.32).y(),
                      sub.width() * 0.80, sub.height() * 0.36)
        path = QPainterPath()
        path.addRoundedRect(body, sub.width() * 0.10, sub.width() * 0.10)
        p.drawPath(path)
        p.drawLine(PT(0.50, 0.32), PT(0.50, 0.16))
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        p.drawEllipse(PT(0.50, 0.13), s * 0.05, s * 0.05)
        p.drawEllipse(PT(0.30, 0.78), s * 0.10, s * 0.10)
        p.drawEllipse(PT(0.70, 0.78), s * 0.10, s * 0.10)

    elif kind == "book":
        path = QPainterPath()
        path.moveTo(PT(0.10, 0.30))
        path.lineTo(PT(0.10, 0.82))
        path.lineTo(PT(0.50, 0.72))
        path.lineTo(PT(0.50, 0.20))
        path.moveTo(PT(0.90, 0.30))
        path.lineTo(PT(0.90, 0.82))
        path.lineTo(PT(0.50, 0.72))
        p.drawPath(path)
        p.drawLine(PT(0.50, 0.20), PT(0.50, 0.72))
        p.drawLine(PT(0.20, 0.50), PT(0.40, 0.46))
        p.drawLine(PT(0.60, 0.46), PT(0.80, 0.50))

    elif kind == "battery":
        body = QRectF(PT(0.08, 0.30).x(), PT(0.08, 0.30).y(),
                      sub.width() * 0.74, sub.height() * 0.40)
        p.drawRoundedRect(body, sub.width() * 0.06, sub.width() * 0.06)
        cap = QRectF(PT(0.84, 0.42).x(), PT(0.84, 0.42).y(),
                     sub.width() * 0.08, sub.height() * 0.16)
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        p.drawRoundedRect(cap, sub.width() * 0.02, sub.width() * 0.02)
        for i in range(3):
            x = 0.16 + i * 0.18
            r = QRectF(PT(x, 0.40).x(), PT(x, 0.40).y(),
                       sub.width() * 0.10, sub.height() * 0.20)
            p.drawRoundedRect(r, sub.width() * 0.02, sub.width() * 0.02)

    elif kind == "gripper":
        p.drawLine(PT(0.30, 0.82), PT(0.70, 0.82))
        path = QPainterPath()
        path.moveTo(PT(0.40, 0.82)); path.lineTo(PT(0.40, 0.52))
        path.moveTo(PT(0.60, 0.82)); path.lineTo(PT(0.60, 0.52))
        path.moveTo(PT(0.40, 0.52)); path.lineTo(PT(0.22, 0.20))
        path.moveTo(PT(0.60, 0.52)); path.lineTo(PT(0.78, 0.20))
        p.drawPath(path)

    elif kind == "door":
        path = QPainterPath()
        path.moveTo(PT(0.20, 0.90))
        path.lineTo(PT(0.20, 0.40))
        path.cubicTo(PT(0.20, 0.10), PT(0.80, 0.10), PT(0.80, 0.40))
        path.lineTo(PT(0.80, 0.90))
        p.drawPath(path)
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        p.drawEllipse(PT(0.66, 0.58), s * 0.04, s * 0.04)

    elif kind == "palette":
        oval = QRectF(PT(0.10, 0.20).x(), PT(0.10, 0.20).y(),
                      sub.width() * 0.80, sub.height() * 0.62)
        p.drawEllipse(oval)
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        for x, y in [(0.30, 0.40), (0.50, 0.32), (0.70, 0.40), (0.65, 0.62)]:
            p.drawEllipse(PT(x, y), s * 0.05, s * 0.05)

    elif kind == "music":
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        p.save()
        p.translate(PT(0.36, 0.78))
        p.rotate(-18)
        p.drawEllipse(QPointF(0, 0), s * 0.13, s * 0.10)
        p.restore()
        p.setBrush(Qt.NoBrush); p.setPen(pen)
        p.drawLine(PT(0.46, 0.74), PT(0.46, 0.18))
        path = QPainterPath()
        path.moveTo(PT(0.46, 0.18))
        path.cubicTo(PT(0.78, 0.24), PT(0.72, 0.50), PT(0.55, 0.55))
        p.drawPath(path)

    elif kind == "bath":
        head = QRectF(PT(0.18, 0.24).x(), PT(0.18, 0.24).y(),
                      sub.width() * 0.64, sub.height() * 0.14)
        p.drawRoundedRect(head, sub.width() * 0.04, sub.width() * 0.04)
        p.drawLine(PT(0.50, 0.08), PT(0.50, 0.24))
        for x in [0.28, 0.45, 0.62, 0.78]:
            p.drawLine(PT(x, 0.46), PT(x, 0.78))

    elif kind == "tree":
        p.drawLine(PT(0.50, 0.92), PT(0.50, 0.62))
        path = QPainterPath()
        path.moveTo(PT(0.50, 0.10))
        path.lineTo(PT(0.20, 0.62))
        path.lineTo(PT(0.80, 0.62))
        path.closeSubpath()
        p.drawPath(path)

    elif kind == "food":
        path = QPainterPath()
        path.moveTo(PT(0.10, 0.55))
        path.cubicTo(PT(0.20, 0.92), PT(0.80, 0.92), PT(0.90, 0.55))
        p.drawPath(path)
        p.drawLine(PT(0.10, 0.55), PT(0.90, 0.55))
        for x in [0.35, 0.50, 0.65]:
            steam = QPainterPath()
            steam.moveTo(PT(x, 0.42))
            steam.cubicTo(PT(x + 0.06, 0.32), PT(x - 0.06, 0.24), PT(x, 0.12))
            p.drawPath(steam)

    elif kind == "bookshelf":
        outer = QRectF(PT(0.15, 0.15).x(), PT(0.15, 0.15).y(),
                       sub.width() * 0.70, sub.height() * 0.78)
        p.drawRoundedRect(outer, sub.width() * 0.04, sub.width() * 0.04)
        p.drawLine(PT(0.30, 0.20), PT(0.30, 0.88))
        p.drawLine(PT(0.45, 0.20), PT(0.45, 0.88))
        p.drawLine(PT(0.60, 0.30), PT(0.60, 0.88))
        p.drawLine(PT(0.72, 0.20), PT(0.72, 0.88))
        p.drawLine(PT(0.15, 0.55), PT(0.85, 0.55))

    elif kind == "classroom":
        outer = QRectF(PT(0.10, 0.18).x(), PT(0.10, 0.18).y(),
                       sub.width() * 0.80, sub.height() * 0.56)
        p.drawRoundedRect(outer, sub.width() * 0.04, sub.width() * 0.04)
        p.drawLine(PT(0.25, 0.38), PT(0.55, 0.38))
        p.drawLine(PT(0.25, 0.55), PT(0.65, 0.55))
        p.drawLine(PT(0.30, 0.74), PT(0.24, 0.92))
        p.drawLine(PT(0.70, 0.74), PT(0.76, 0.92))

    elif kind == "block":
        outer = QRectF(PT(0.20, 0.20).x(), PT(0.20, 0.20).y(),
                       sub.width() * 0.60, sub.height() * 0.60)
        p.drawRoundedRect(outer, sub.width() * 0.06, sub.width() * 0.06)
        p.drawLine(PT(0.50, 0.20), PT(0.50, 0.80))
        p.drawLine(PT(0.20, 0.50), PT(0.80, 0.50))

    elif kind == "ball":
        oval = QRectF(PT(0.18, 0.18).x(), PT(0.18, 0.18).y(),
                      sub.width() * 0.64, sub.height() * 0.64)
        p.drawEllipse(oval)
        path = QPainterPath()
        path.moveTo(PT(0.18, 0.50))
        path.cubicTo(PT(0.40, 0.40), PT(0.60, 0.40), PT(0.82, 0.50))
        p.drawPath(path)
        path2 = QPainterPath()
        path2.moveTo(PT(0.50, 0.18))
        path2.cubicTo(PT(0.40, 0.40), PT(0.60, 0.60), PT(0.50, 0.82))
        p.drawPath(path2)

    elif kind == "robot":
        outer = QRectF(PT(0.20, 0.30).x(), PT(0.20, 0.30).y(),
                       sub.width() * 0.60, sub.height() * 0.50)
        p.drawRoundedRect(outer, sub.width() * 0.10, sub.width() * 0.10)
        p.drawLine(PT(0.50, 0.30), PT(0.50, 0.16))
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        p.drawEllipse(PT(0.50, 0.13), s * 0.05, s * 0.05)
        p.drawEllipse(PT(0.36, 0.50), s * 0.05, s * 0.05)
        p.drawEllipse(PT(0.64, 0.50), s * 0.05, s * 0.05)
        p.setBrush(Qt.NoBrush); p.setPen(pen)
        p.drawLine(PT(0.40, 0.66), PT(0.60, 0.66))

    elif kind == "joystick":
        base = QRectF(PT(0.20, 0.74).x(), PT(0.20, 0.74).y(),
                      sub.width() * 0.60, sub.height() * 0.16)
        p.drawRoundedRect(base, sub.width() * 0.06, sub.width() * 0.06)
        p.drawLine(PT(0.50, 0.74), PT(0.50, 0.30))
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        p.drawEllipse(PT(0.50, 0.24), s * 0.10, s * 0.10)

    elif kind == "pin":
        path = QPainterPath()
        path.moveTo(PT(0.50, 0.95))
        path.cubicTo(PT(0.10, 0.55), PT(0.18, 0.10), PT(0.50, 0.10))
        path.cubicTo(PT(0.82, 0.10), PT(0.90, 0.55), PT(0.50, 0.95))
        p.drawPath(path)
        p.drawEllipse(PT(0.50, 0.40), s * 0.10, s * 0.10)

    elif kind == "hug":
        p.drawEllipse(PT(0.34, 0.32), s * 0.13, s * 0.13)
        p.drawEllipse(PT(0.66, 0.32), s * 0.13, s * 0.13)
        path = QPainterPath()
        path.moveTo(PT(0.16, 0.86))
        path.cubicTo(PT(0.16, 0.58), PT(0.42, 0.55), PT(0.50, 0.70))
        path.cubicTo(PT(0.58, 0.55), PT(0.84, 0.58), PT(0.84, 0.86))
        p.drawPath(path)

    elif kind == "sparkle":
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        path = QPainterPath()
        path.moveTo(PT(0.50, 0.05))
        path.lineTo(PT(0.55, 0.45))
        path.lineTo(PT(0.95, 0.50))
        path.lineTo(PT(0.55, 0.55))
        path.lineTo(PT(0.50, 0.95))
        path.lineTo(PT(0.45, 0.55))
        path.lineTo(PT(0.05, 0.50))
        path.lineTo(PT(0.45, 0.45))
        path.closeSubpath()
        p.drawPath(path)

    elif kind == "rainbow":
        for i, frac in enumerate([0.92, 0.72, 0.52]):
            colors = [COLORS["primary"], COLORS["accent"], COLORS["sky"]]
            arc_pen = QPen(QColor(colors[i]), lw)
            arc_pen.setCapStyle(Qt.RoundCap)
            p.setPen(arc_pen)
            r = QRectF(
                rect.center().x() - s * frac / 2,
                rect.center().y() - s * frac / 4,
                s * frac,
                s * frac,
            )
            p.drawArc(r, 0, 180 * 16)

    elif kind == "smile":
        oval = QRectF(PT(0.15, 0.15).x(), PT(0.15, 0.15).y(),
                      sub.width() * 0.70, sub.height() * 0.70)
        p.drawEllipse(oval)
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        p.drawEllipse(PT(0.38, 0.42), s * 0.04, s * 0.04)
        p.drawEllipse(PT(0.62, 0.42), s * 0.04, s * 0.04)
        p.setBrush(Qt.NoBrush); p.setPen(pen)
        smile_rect = QRectF(PT(0.32, 0.42).x(), PT(0.32, 0.42).y(),
                            sub.width() * 0.36, sub.height() * 0.32)
        p.drawArc(smile_rect, 200 * 16, 140 * 16)

    elif kind == "wave":
        # 손 흔들기 — 손바닥 + 손가락 5개
        path = QPainterPath()
        path.moveTo(PT(0.30, 0.85))
        path.lineTo(PT(0.30, 0.50))
        for x in [0.34, 0.46, 0.58, 0.70]:
            path.moveTo(PT(x, 0.50))
            path.lineTo(PT(x, 0.20))
        p.drawPath(path)
        p.drawLine(PT(0.30, 0.50), PT(0.74, 0.50))

    elif kind == "list":
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        for y in [0.28, 0.50, 0.72]:
            p.drawEllipse(PT(0.20, y), s * 0.05, s * 0.05)
        p.setPen(pen)
        for y in [0.28, 0.50, 0.72]:
            p.drawLine(PT(0.34, y), PT(0.84, y))

    elif kind == "bowtie":
        path = QPainterPath()
        path.moveTo(PT(0.10, 0.20))
        path.lineTo(PT(0.10, 0.80))
        path.lineTo(PT(0.50, 0.50))
        path.lineTo(PT(0.90, 0.80))
        path.lineTo(PT(0.90, 0.20))
        path.lineTo(PT(0.50, 0.50))
        path.closeSubpath()
        p.drawPath(path)

    elif kind == "play":
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        path = QPainterPath()
        path.moveTo(PT(0.30, 0.18))
        path.lineTo(PT(0.85, 0.50))
        path.lineTo(PT(0.30, 0.82))
        path.closeSubpath()
        p.drawPath(path)

    elif kind == "dot":
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        p.drawEllipse(PT(0.50, 0.50), s * 0.12, s * 0.12)

    elif kind == "cpu":
        # 칩 본체 + 네 변의 핀 + 내부 점 4개
        body = QRectF(PT(0.25, 0.25).x(), PT(0.25, 0.25).y(),
                      sub.width() * 0.50, sub.height() * 0.50)
        p.drawRoundedRect(body, sub.width() * 0.05, sub.width() * 0.05)
        for t in (0.40, 0.60):
            p.drawLine(PT(t, 0.10), PT(t, 0.25))
            p.drawLine(PT(t, 0.75), PT(t, 0.90))
            p.drawLine(PT(0.10, t), PT(0.25, t))
            p.drawLine(PT(0.75, t), PT(0.90, t))
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        for x, y in [(0.40, 0.40), (0.60, 0.40), (0.40, 0.60), (0.60, 0.60)]:
            p.drawEllipse(PT(x, y), s * 0.035, s * 0.035)

    elif kind == "radar":
        # 좌하단 원점에서 뻗어나가는 동심 4분원 + 스캔 선
        cx, cy = 0.18, 0.82
        for frac in (0.45, 0.70, 0.95):
            r = QRectF(PT(cx - frac, cy - frac).x(), PT(cx - frac, cy - frac).y(),
                       sub.width() * frac * 2, sub.height() * frac * 2)
            p.drawArc(r, 0, 90 * 16)
        p.drawLine(PT(cx, cy), PT(cx + 0.78, cy - 0.30))
        p.setBrush(qcol); p.setPen(Qt.NoPen)
        p.drawEllipse(PT(cx, cy), s * 0.05, s * 0.05)

    else:
        # 알 수 없는 kind — 빈 사각 placeholder
        p.drawRoundedRect(sub, sub.width() * 0.12, sub.width() * 0.12)

    p.restore()


class Icon(QWidget):
    """단일 아이콘 위젯."""

    def __init__(self, kind: str, size: int = 20, color: str | None = None,
                 parent=None):
        super().__init__(parent)
        self.kind = kind
        self.color = color or COLORS["text"]
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_color(self, color: str) -> None:
        self.color = color
        self.update()

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        draw_icon(p, self.kind, QRectF(self.rect()), self.color)


class IconText(QWidget):
    """[Icon][Label] 가로 조합. 카드 제목·메트릭 라벨 등에 쓴다."""

    def __init__(self, kind: str, text: str, *, size: int = 18,
                 color: str | None = None, text_color: str | None = None,
                 bold: bool = False, font_pt: int = 13, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.icon = Icon(kind, size=size, color=color or COLORS["text_soft"])
        self.label = QLabel(text)
        self.label.setStyleSheet(
            f"color: {text_color or COLORS['text']}; "
            f"font-size: {font_pt}px; "
            f"font-weight: {'700' if bold else '500'}; "
            f"background: transparent;"
        )
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self.icon, 0, Qt.AlignVCenter)
        lay.addWidget(self.label, 1, Qt.AlignVCenter)

    def set_text(self, text: str) -> None:
        self.label.setText(text)


def make_qicon(kind: str, size: int = 32, color: str | None = None) -> QIcon:
    """QPushButton.setIcon 등에 쓰기 위한 QIcon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    draw_icon(p, kind, QRectF(0, 0, size, size), color or COLORS["text"])
    p.end()
    return QIcon(pix)


# --------------------------------------------------------------------------
# 카드 / 뱃지 / 메트릭
# --------------------------------------------------------------------------


class Card(QFrame):
    """둥근 모서리 흰 카드. 제목(선택) + 본문 레이아웃."""

    def __init__(self, title: str | None = None, soft: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("cardSoft" if soft else "card")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(18, 16, 18, 18)
        self._outer.setSpacing(12)

        if title is not None:
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(title)
            lbl.setObjectName("cardTitle")
            row.addWidget(lbl)
            row.addStretch(1)
            self._title_row = row
            self._outer.addLayout(row)
        else:
            self._title_row = None

        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self._outer.addLayout(self.body)

    def add_title_widget(self, w: QWidget) -> None:
        if self._title_row is not None:
            self._title_row.addWidget(w)


class StatusBadge(QLabel):
    """둥근 알약 뱃지. 색상은 상태에 따라 다르게."""

    def __init__(self, text: str, color_hex: str, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
        self.setMinimumHeight(26)
        self.set_status(text, color_hex)

    def set_status(self, text: str, color_hex: str) -> None:
        self.setText(text)
        soft = soften(color_hex, 0.18)
        self.setStyleSheet(
            f"""
            QLabel {{
                background: {soft};
                color: {color_hex};
                border-radius: 13px;
                padding: 3px 14px;
                font-size: 12px;
                font-weight: 700;
            }}
            """
        )


class MetricRow(QWidget):
    """라벨(왼쪽) + 값(오른쪽)."""

    def __init__(self, label: str, value: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._lbl = QLabel(label)
        self._lbl.setObjectName("metricLabel")
        self._val = QLabel(value)
        self._val.setObjectName("metricValue")
        self._val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self._lbl)
        lay.addStretch(1)
        lay.addWidget(self._val)

    def set_value(self, value: str) -> None:
        self._val.setText(value)


class IconMetricRow(QWidget):
    """[Icon][label]   value — 시스템 카드 안에서 쓴다."""

    def __init__(self, kind: str, label: str, value: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.icon = Icon(kind, size=16, color=COLORS["text_muted"])
        self._lbl = QLabel(label)
        self._lbl.setObjectName("metricLabel")
        self._val = QLabel(value)
        self._val.setObjectName("metricValue")
        self._val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.icon, 0, Qt.AlignVCenter)
        lay.addWidget(self._lbl)
        lay.addStretch(1)
        lay.addWidget(self._val)

    def set_value(self, value: str) -> None:
        self._val.setText(value)


class BatteryBar(QWidget):
    """배터리 가로 바 + 퍼센트."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pct = 87
        self.setMinimumHeight(36)

    def set_pct(self, pct: int) -> None:
        self._pct = max(0, min(100, int(pct)))
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        full = QRectF(self.rect())
        rect = full.adjusted(0, 6, -36, -6)

        p.setPen(QPen(QColor(COLORS["border_strong"]), 1.6))
        p.setBrush(QColor(COLORS["track"]))
        p.drawRoundedRect(rect, 9, 9)

        cap = QRectF(rect.right() + 2, rect.top() + rect.height() * 0.25,
                     6, rect.height() * 0.5)
        p.setBrush(QColor(COLORS["border_strong"]))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(cap, 2, 2)

        if self._pct > 0:
            inner = rect.adjusted(3, 3, -3, -3)
            inner.setWidth(inner.width() * self._pct / 100.0)
            color = (
                COLORS["danger"] if self._pct < 20
                else COLORS["warning"] if self._pct < 40
                else COLORS["success"]
            )
            p.setBrush(QColor(color))
            p.drawRoundedRect(inner, 6, 6)

        p.setPen(QColor(COLORS["text"]))
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSize(11)
        p.setFont(f)
        label_rect = QRectF(rect.right() + 12, rect.top(), 50, rect.height())
        p.drawText(label_rect, Qt.AlignVCenter | Qt.AlignLeft, f"{self._pct}%")


# --------------------------------------------------------------------------
# StatChip — 단일 행 파스텔 stat 카드 (시스템 상태 우측 스택용)
# --------------------------------------------------------------------------


class _ChipBar(QWidget):
    """StatChip 내부 얇은 % 바. 배터리는 잔량에 따라 색이 바뀜."""

    def __init__(self, accent_hex: str, auto_color: bool = False, parent=None):
        super().__init__(parent)
        self._accent = accent_hex
        self._auto = auto_color
        self._pct = 0
        self.setFixedHeight(6)

    def set_pct(self, pct: int) -> None:
        self._pct = max(0, min(100, int(pct)))
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 170))
        p.drawRoundedRect(rect, 3, 3)
        if self._pct > 0:
            fill = QRectF(rect)
            fill.setWidth(fill.width() * self._pct / 100.0)
            if self._auto:
                col = (COLORS["danger"] if self._pct < 20
                       else COLORS["warning"] if self._pct < 40
                       else COLORS["success"])
            else:
                col = self._accent
            p.setBrush(QColor(col))
            p.drawRoundedRect(fill, 3, 3)


class StatChip(QFrame):
    """파스텔 톤 단일 행 stat 카드.

    좌측: 흰 원형 아바타 + 아이콘
    중앙: 라벨(작게) + (옵션) 보조 문구
    우측: 값(크게)
    하단(옵션): 얇은 % 바

    accent_hex 가 파스텔 배경/포인트 색을 결정한다.
    with_bar=True 면 하단에 % 바 추가.
    battery=True 면 % 바 색이 잔량에 따라 자동 변경.
    """

    def __init__(self,
                 icon_kind: str,
                 label: str,
                 value: str,
                 accent_hex: str,
                 with_bar: bool = False,
                 battery: bool = False,
                 parent=None):
        super().__init__(parent)
        self._accent = accent_hex
        bg = soften(accent_hex, 0.20)
        border = soften(accent_hex, 0.55)
        self.setObjectName("statChip")
        self.setStyleSheet(
            f"""
            QFrame#statChip {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 16px;
            }}
            QFrame#statChip QLabel {{ background: transparent; }}
            """
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(64 if with_bar else 54)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 14, 8)
        outer.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.setContentsMargins(0, 0, 0, 0)

        # 흰 원형 아바타 + 아이콘
        avatar = QFrame()
        avatar.setFixedSize(32, 32)
        avatar.setStyleSheet(
            "background: rgba(255,255,255,0.78); "
            "border-radius: 16px; border: none;"
        )
        a_lay = QVBoxLayout(avatar)
        a_lay.setContentsMargins(0, 0, 0, 0)
        a_lay.addWidget(Icon(icon_kind, size=18, color=accent_hex),
                        0, Qt.AlignCenter)
        avatar.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(avatar, 0, Qt.AlignVCenter)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {COLORS['text_soft']}; font-size: 12px; "
            f"font-weight: 700; letter-spacing: 0.3px;"
        )
        row.addWidget(lbl, 0, Qt.AlignVCenter)
        row.addStretch(1)

        self._val = QLabel(value)
        self._val.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 17px; font-weight: 800;"
        )
        self._val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self._val, 0, Qt.AlignVCenter)

        outer.addLayout(row)

        self._bar: _ChipBar | None = None
        if with_bar:
            self._bar = _ChipBar(accent_hex, auto_color=battery)
            outer.addWidget(self._bar)

    def set_value(self, value: str) -> None:
        self._val.setText(value)

    def set_pct(self, pct: int) -> None:
        if self._bar is not None:
            self._bar.set_pct(pct)


# --------------------------------------------------------------------------
# 관절 / 그리퍼
# --------------------------------------------------------------------------


@dataclass
class Joint:
    name: str
    angle: float
    minimum: float = -180
    maximum: float = 180


class JointBar(QWidget):
    def __init__(self, joint: Joint, accent: str, parent=None):
        super().__init__(parent)
        self.joint = joint
        self.accent = accent
        self.setMinimumHeight(28)

    def set_angle(self, angle: float) -> None:
        self.joint.angle = angle
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        f = QFont(self.font())
        f.setPointSize(10)
        p.setFont(f)
        p.setPen(QColor(COLORS["text_muted"]))
        p.drawText(QRectF(0, 0, 60, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, self.joint.name)

        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(COLORS["text"]))
        p.drawText(QRectF(self.width() - 60, 0, 60, self.height()),
                   Qt.AlignVCenter | Qt.AlignRight, f"{self.joint.angle:+6.1f}°")

        track = QRectF(64, self.height() / 2 - 4, self.width() - 64 - 64, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(COLORS["track"]))
        p.drawRoundedRect(track, 4, 4)

        cx = track.left() + track.width() / 2
        p.setPen(QPen(QColor(COLORS["border_strong"]), 1, Qt.DashLine))
        p.drawLine(QPointF(cx, track.top() - 3), QPointF(cx, track.bottom() + 3))

        ratio = max(-1.0, min(1.0,
                              self.joint.angle / max(abs(self.joint.minimum),
                                                     abs(self.joint.maximum))))
        if ratio >= 0:
            fill = QRectF(cx, track.top(), track.width() / 2 * ratio, track.height())
        else:
            w = track.width() / 2 * (-ratio)
            fill = QRectF(cx - w, track.top(), w, track.height())
        p.setBrush(QColor(self.accent))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(fill, 4, 4)


class JointPanel(QWidget):
    def __init__(self, joints: list[Joint], accent: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._bars: list[JointBar] = []
        for j in joints:
            bar = JointBar(j, accent)
            self._bars.append(bar)
            lay.addWidget(bar)

    def update_angles(self, angles: list[float]) -> None:
        for bar, a in zip(self._bars, angles):
            bar.set_angle(a)


class GripperIndicator(QWidget):
    """그리퍼 개폐 시각화. 0=닫힘, 1=열림."""

    def __init__(self, accent: str, parent=None):
        super().__init__(parent)
        self.accent = accent
        self._open = 0.4
        self.setMinimumSize(QSize(150, 130))

    def set_open(self, ratio: float) -> None:
        self._open = max(0.0, min(1.0, ratio))
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()

        base = QRectF(w / 2 - 26, h - 28, 52, 14)
        p.setBrush(QColor(COLORS["border_strong"]))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(base, 4, 4)

        body = QRectF(w / 2 - 18, h - 64, 36, 38)
        p.setBrush(QColor(self.accent))
        p.drawRoundedRect(body, 8, 8)

        finger_h = 44
        spread = 10 + self._open * 38
        cx = w / 2
        top = h - 64 - finger_h
        for sign in (-1, 1):
            x = cx + sign * spread - 3
            p.setBrush(QColor(self.accent))
            p.drawRoundedRect(QRectF(x, top, 6, finger_h), 3, 3)
            p.setBrush(QColor(COLORS["bg_alt"]))
            p.drawRoundedRect(QRectF(x - 2, top - 4, 10, 8), 3, 3)

        f = QFont(self.font())
        f.setBold(True)
        f.setPointSize(11)
        p.setFont(f)
        p.setPen(QColor(COLORS["text"]))
        label = "열림" if self._open > 0.6 else ("닫힘" if self._open < 0.2 else "잡는 중")
        p.drawText(QRectF(0, 8, w, 18), Qt.AlignCenter, label)
        p.setPen(QColor(COLORS["text_muted"]))
        f.setBold(False)
        f.setPointSize(9)
        p.setFont(f)
        p.drawText(QRectF(0, 26, w, 14), Qt.AlignCenter,
                   f"{int(self._open * 100)}% open")


# --------------------------------------------------------------------------
# 작업 큐 — 커스텀 행 위젯 기반
# --------------------------------------------------------------------------


class TaskRow(QWidget):
    """[icon][label] 한 줄. active 상태이면 강조."""

    def __init__(self, kind: str, label: str, accent: str, active: bool = False,
                 parent=None):
        super().__init__(parent)
        self.setMinimumHeight(34)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(10)

        # 진행 인디케이터 (재생 삼각형 vs 빈 점)
        self.indicator = Icon("play" if active else "dot",
                              size=12,
                              color=accent if active else COLORS["border_strong"])
        lay.addWidget(self.indicator, 0, Qt.AlignVCenter)

        self.icon = Icon(kind, size=18,
                         color=COLORS["text"] if active else COLORS["text_muted"])
        lay.addWidget(self.icon, 0, Qt.AlignVCenter)

        self.label = QLabel(label)
        self.label.setStyleSheet(
            f"color: {COLORS['text'] if active else COLORS['text_muted']}; "
            f"font-size: 13px; "
            f"font-weight: {'700' if active else '500'}; "
            f"background: transparent;"
        )
        lay.addWidget(self.label, 1, Qt.AlignVCenter)

        if active:
            self.setStyleSheet(
                f"TaskRow {{ background: {soften(accent, 0.20)}; "
                f"border-radius: 10px; }}"
            )


class TaskQueue(QWidget):
    """작업 큐 — TaskRow 들을 쌓는 컨테이너."""

    def __init__(self, accent: str | None = None, parent=None):
        super().__init__(parent)
        self.accent = accent or COLORS["primary"]
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(2)

    def set_tasks(self, tasks: list[tuple[str, str]]) -> None:
        """tasks: [(icon_kind, label), ...] — 첫 항목이 진행 중."""
        # 비우기
        while self._lay.count():
            it = self._lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

        for i, (kind, label) in enumerate(tasks):
            row = TaskRow(kind, label, self.accent, active=(i == 0))
            self._lay.addWidget(row)


# --------------------------------------------------------------------------
# 맵 뷰 (GogoPing)
# --------------------------------------------------------------------------


@dataclass
class Room:
    rect: QRectF
    label: str
    icon_kind: str
    color: str


class MapView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._rooms = [
            Room(QRectF(2, 4, 26, 28),  "출입구",   "door",       COLORS["sun"]),
            Room(QRectF(32, 4, 30, 32), "1반 교실", "palette",    COLORS["lavender"]),
            Room(QRectF(66, 4, 32, 32), "2반 교실", "music",      COLORS["sky"]),
            Room(QRectF(2, 38, 22, 18), "화장실",   "bath",       COLORS["mint"]),
            Room(QRectF(28, 40, 70, 28), "운동장",  "tree",       COLORS["primary_dim"]),
            Room(QRectF(2, 60, 24, 36), "식당",     "food",       COLORS["accent"]),
            Room(QRectF(30, 72, 68, 24), "도서실",  "bookshelf",  COLORS["mint"]),
        ]
        self._path = [
            QPointF(15, 18), QPointF(47, 20), QPointF(82, 20),
            QPointF(82, 54), QPointF(63, 84), QPointF(15, 78),
        ]
        self._t = 0.0

    def step(self, dt: float = 0.012) -> None:
        self._t = (self._t + dt) % len(self._path)
        self.update()

    def _robot_pos(self):
        n = len(self._path)
        i = int(self._t) % n
        j = (i + 1) % n
        f = self._t - int(self._t)
        a, b = self._path[i], self._path[j]
        x = a.x() + (b.x() - a.x()) * f
        y = a.y() + (b.y() - a.y()) * f
        heading = math.atan2(b.y() - a.y(), b.x() - a.x())
        return QPointF(x, y), heading

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        sx, sy = w / 100.0, h / 100.0

        p.fillRect(self.rect(), QColor(COLORS["bg_alt"]))
        p.setPen(QPen(QColor(COLORS["border"]), 1))
        for gx in range(0, 101, 10):
            p.drawLine(int(gx * sx), 0, int(gx * sx), h)
        for gy in range(0, 101, 10):
            p.drawLine(0, int(gy * sy), w, int(gy * sy))

        f = QFont(self.font())
        f.setPointSize(10)
        f.setBold(True)
        p.setFont(f)
        for room in self._rooms:
            r = QRectF(room.rect.x() * sx, room.rect.y() * sy,
                       room.rect.width() * sx, room.rect.height() * sy)
            p.setBrush(QColor(soften(room.color, 0.35)))
            p.setPen(QPen(QColor(room.color), 1.6))
            p.drawRoundedRect(r, 12, 12)

            # 좌상단에 아이콘 + 우측에 라벨
            icon_rect = QRectF(r.left() + 6, r.top() + 6, 22, 22)
            draw_icon(p, room.icon_kind, icon_rect, COLORS["text_soft"], line_ratio=0.14)
            p.setPen(QColor(COLORS["text_soft"]))
            text_rect = QRectF(r.left() + 32, r.top() + 6, r.width() - 38, 22)
            p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, room.label)

        # 경로
        path = QPainterPath()
        first = self._path[0]
        path.moveTo(first.x() * sx, first.y() * sy)
        for pt in self._path[1:]:
            path.lineTo(pt.x() * sx, pt.y() * sy)
        path.lineTo(first.x() * sx, first.y() * sy)
        pen = QPen(QColor(COLORS["primary"]), 2.5)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        for pt in self._path:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(COLORS["primary"]))
            p.drawEllipse(QPointF(pt.x() * sx, pt.y() * sy), 4, 4)
            p.setBrush(QColor(COLORS["panel"]))
            p.drawEllipse(QPointF(pt.x() * sx, pt.y() * sy), 1.6, 1.6)

        # 로봇
        pos, heading = self._robot_pos()
        rx, ry = pos.x() * sx, pos.y() * sy
        glow = QRadialGradient(QPointF(rx, ry), 22)
        glow.setColorAt(0, QColor(126, 200, 227, 110))
        glow.setColorAt(1, QColor(126, 200, 227, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(rx, ry), 22, 22)

        p.setBrush(QColor(COLORS["sky"]))
        p.setPen(QPen(QColor("#3D8FB0"), 1.5))
        p.drawEllipse(QPointF(rx, ry), 11, 11)

        ax = rx + math.cos(heading) * 18
        ay = ry + math.sin(heading) * 18
        arrow = QPolygonF([
            QPointF(ax, ay),
            QPointF(ax - math.cos(heading - 0.5) * 8,
                    ay - math.sin(heading - 0.5) * 8),
            QPointF(ax - math.cos(heading + 0.5) * 8,
                    ay - math.sin(heading + 0.5) * 8),
        ])
        p.setBrush(QColor(COLORS["primary"]))
        p.setPen(Qt.NoPen)
        p.drawPolygon(arrow)

        # 로봇 라벨 (이모지 없이)
        label_rect = QRectF(rx - 50, ry + 14, 100, 18)
        p.setBrush(QColor(255, 255, 255, 220))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(label_rect, 9, 9)
        p.setPen(QColor(COLORS["text"]))
        f.setPointSize(10)
        p.setFont(f)
        p.drawText(label_rect, Qt.AlignCenter, "GogoPing")


# --------------------------------------------------------------------------
# 카메라 뷰
# --------------------------------------------------------------------------


class CameraView(QWidget):
    """가짜 카메라 피드. 파스텔 교실 풍경 + LIVE 뱃지."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._tick = 0
        self._frame = 0

    def step(self) -> None:
        self._tick += 1
        if self._tick % 2 == 0:
            self._frame += 1
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())

        path = QPainterPath()
        path.addRoundedRect(rect, 14, 14)
        p.setClipPath(path)

        floor_y = rect.height() * 0.62
        wall = QLinearGradient(0, 0, 0, floor_y)
        wall.setColorAt(0, QColor("#FFE9F2"))
        wall.setColorAt(1, QColor("#FFF4E1"))
        p.fillRect(QRectF(0, 0, rect.width(), floor_y), QBrush(wall))

        floor = QLinearGradient(0, floor_y, 0, rect.height())
        floor.setColorAt(0, QColor("#E8C9A4"))
        floor.setColorAt(1, QColor("#D9B488"))
        p.fillRect(QRectF(0, floor_y, rect.width(), rect.height() - floor_y),
                   QBrush(floor))

        # 창문
        win_w = rect.width() * 0.22
        win_x = rect.width() * 0.08
        win = QRectF(win_x, rect.height() * 0.10, win_w, rect.height() * 0.36)
        win_grad = QLinearGradient(0, win.top(), 0, win.bottom())
        win_grad.setColorAt(0, QColor("#BFE3F2"))
        win_grad.setColorAt(1, QColor("#E8F6FB"))
        p.setBrush(QBrush(win_grad))
        p.setPen(QPen(QColor("#9DBCC9"), 2))
        p.drawRoundedRect(win, 8, 8)
        p.drawLine(QPointF(win.center().x(), win.top()),
                   QPointF(win.center().x(), win.bottom()))
        p.drawLine(QPointF(win.left(), win.center().y()),
                   QPointF(win.right(), win.center().y()))
        p.setBrush(QColor("#FFD56B"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(win.right() - 18, win.top() + 18), 10, 10)

        # 칠판
        bb_w = rect.width() * 0.35
        bb = QRectF(rect.width() * 0.40, rect.height() * 0.12,
                    bb_w, rect.height() * 0.32)
        p.setBrush(QColor("#7DB18A"))
        p.setPen(QPen(QColor("#9C7B5A"), 4))
        p.drawRoundedRect(bb, 4, 4)
        p.setPen(QColor("#FFFFFF"))
        f = QFont(self.font())
        f.setPointSize(13)
        f.setBold(True)
        p.setFont(f)
        p.drawText(bb, Qt.AlignCenter, "오늘의 인사\n안녕하세요")

        # 블록 더미
        block_x = rect.width() * 0.18
        block_y = floor_y + 6
        colors = ["#FF8FAB", "#FFC371", "#7EC8E3", "#A8E6CF"]
        for i in range(4):
            offset = math.sin((self._frame + i * 7) * 0.04) * 0.6
            r = QRectF(block_x + i * 22, block_y - 24 + offset, 20, 24)
            p.setBrush(QColor(colors[i]))
            p.setPen(QPen(QColor(0, 0, 0, 30), 1))
            p.drawRoundedRect(r, 4, 4)

        # 공
        ball_x = rect.width() * 0.78 + math.sin(self._frame * 0.05) * 8
        ball_y = floor_y + 16
        p.setBrush(QColor("#FF8FAB"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(ball_x, ball_y), 16, 16)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QPointF(ball_x - 4, ball_y - 4), 4, 4)

        # 노이즈
        rng = random.Random(self._frame)
        p.setPen(Qt.NoPen)
        for _ in range(40):
            x = rng.uniform(0, rect.width())
            y = rng.uniform(0, rect.height())
            p.setBrush(QColor(255, 255, 255, rng.randint(15, 40)))
            p.drawEllipse(QPointF(x, y), 1.0, 1.0)

        # 비네팅
        vg = QRadialGradient(rect.center(),
                             max(rect.width(), rect.height()) * 0.7)
        vg.setColorAt(0.6, QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, QColor(0, 0, 0, 70))
        p.setBrush(QBrush(vg))
        p.drawRect(rect)

        # LIVE 뱃지 (이모지 없이 — 깜박이는 점 + 텍스트)
        live = QRectF(12, 12, 70, 24)
        p.setBrush(QColor(0, 0, 0, 130))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(live, 12, 12)
        dot_color = (QColor(COLORS["danger"]) if self._frame % 30 < 15
                     else QColor("#FFFFFF"))
        p.setBrush(dot_color)
        p.drawEllipse(QPointF(24, 24), 4, 4)
        p.setPen(QColor("#FFFFFF"))
        f.setPointSize(10)
        p.setFont(f)
        p.drawText(live.adjusted(34, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, "LIVE")

        # 타임스탬프
        ts = QRectF(rect.width() - 110, 12, 96, 24)
        p.setBrush(QColor(0, 0, 0, 130))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(ts, 12, 12)
        p.setPen(QColor("#FFFFFF"))
        from datetime import datetime
        p.drawText(ts, Qt.AlignCenter, datetime.now().strftime("%H:%M:%S"))

        # 해상도
        res = QRectF(rect.width() - 80, rect.height() - 30, 68, 20)
        p.setBrush(QColor(0, 0, 0, 110))
        p.drawRoundedRect(res, 9, 9)
        p.setPen(QColor("#FFFFFF"))
        f.setPointSize(9)
        p.setFont(f)
        p.drawText(res, Qt.AlignCenter, "640x480")


# --------------------------------------------------------------------------
# 컴퍼스 다이얼
# --------------------------------------------------------------------------


class CompassDial(QWidget):
    def __init__(self, accent: str, parent=None):
        super().__init__(parent)
        self.accent = accent
        self.heading = 45.0
        self.speed = 0.3
        self.setMinimumSize(QSize(160, 160))

    def set_state(self, heading: float, speed: float) -> None:
        self.heading = heading
        self.speed = max(0, min(1, speed))
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height())
        cx, cy = self.width() / 2, self.height() / 2
        r = side / 2 - 6

        p.setBrush(QColor(COLORS["bg_alt"]))
        p.setPen(QPen(QColor(COLORS["border_strong"]), 1.5))
        p.drawEllipse(QPointF(cx, cy), r, r)

        bbox = QRectF(cx - r + 8, cy - r + 8, (r - 8) * 2, (r - 8) * 2)
        pen = QPen(QColor(COLORS["track"]), 8)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(bbox, 220 * 16, -260 * 16)
        pen2 = QPen(QColor(self.accent), 8)
        pen2.setCapStyle(Qt.RoundCap)
        p.setPen(pen2)
        p.drawArc(bbox, 220 * 16, int(-260 * 16 * self.speed))

        f = QFont(self.font())
        f.setBold(True)
        f.setPointSize(10)
        p.setFont(f)
        p.setPen(QColor(COLORS["text_muted"]))
        for label, ang in (("N", 0), ("E", 90), ("S", 180), ("W", 270)):
            rad = math.radians(ang - 90)
            tx = cx + math.cos(rad) * (r - 18) - 6
            ty = cy + math.sin(rad) * (r - 18) - 8
            p.drawText(QRectF(tx, ty, 14, 14), Qt.AlignCenter, label)

        rad = math.radians(self.heading - 90)
        tip = QPointF(cx + math.cos(rad) * (r - 30),
                      cy + math.sin(rad) * (r - 30))
        rad_l = math.radians(self.heading - 90 + 140)
        rad_r = math.radians(self.heading - 90 - 140)
        left = QPointF(cx + math.cos(rad_l) * 10,
                       cy + math.sin(rad_l) * 10)
        right = QPointF(cx + math.cos(rad_r) * 10,
                        cy + math.sin(rad_r) * 10)
        p.setBrush(QColor(self.accent))
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([tip, left, right]))

        p.setBrush(QColor(COLORS["panel"]))
        p.setPen(QPen(QColor(COLORS["border_strong"]), 1.5))
        p.drawEllipse(QPointF(cx, cy), 8, 8)

        p.setPen(QColor(COLORS["text"]))
        f.setPointSize(13)
        p.setFont(f)
        p.drawText(QRectF(0, cy + r * 0.45, self.width(), 18),
                   Qt.AlignCenter, f"{self.speed * 0.6:.2f} m/s")


# --------------------------------------------------------------------------
# 유틸
# --------------------------------------------------------------------------


def soften(hex_color: str, alpha: float) -> str:
    """hex 색을 흰색과 섞어 연하게."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    r2 = int(255 - (255 - r) * alpha)
    g2 = int(255 - (255 - g) * alpha)
    b2 = int(255 - (255 - b) * alpha)
    return f"#{r2:02X}{g2:02X}{b2:02X}"
