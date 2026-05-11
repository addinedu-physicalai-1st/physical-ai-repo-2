"""Teleop 카드 — admin-ui 의 GogoPing 디버깅용 직접 조작 도구.

키보드/버튼 입력 → Control Server REST 로 cmd_vel publish.
WS 로 odom/scan 수신 → 미니뷰 표시.
rclpy 직접 import 금지 (Control Server 경유).
"""

from __future__ import annotations

import json
import math
import pathlib
from typing import Callable

from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, QSize
from PyQt5.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from theme import COLORS
from widgets import Card, StatusBadge, soften

SendCmdFn = Callable[[float, float], None]

CMD_TICK_MS = 100
HEALTH_TICK_MS = 5000

# D-pad 버튼 글리프 — 안정적인 유니코드 삼각형
_GLYPH = {"up": "▲", "down": "▼", "left": "◀", "right": "▶"}

# 화살표 키 → 방향 kind 매핑 (키보드 입력 시 버튼 setDown 으로 시각 피드백)
_KEY_TO_KIND = {
    Qt.Key_Up: "up",
    Qt.Key_Down: "down",
    Qt.Key_Left: "left",
    Qt.Key_Right: "right",
}


def _load_vic_ip(json_path: pathlib.Path) -> str:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        return str(data.get("vic", {}).get("ip", "?"))
    except (FileNotFoundError, ValueError, OSError):
        return "?"


# --------------------------------------------------------------------------
# DirectionalPad — 5 버튼 + 페인트된 라운드 패드 배경
# --------------------------------------------------------------------------


class DirectionalPad(QWidget):
    """좌측 조이스틱 풍 D-pad. 4 방향 버튼 + STOP 가운데."""

    PAD_SIZE = 224
    BTN_SIZE = 60

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(self.PAD_SIZE, self.PAD_SIZE))
        self._active: set[str] = set()  # {"up","down","left","right"}

        grid = QGridLayout(self)
        grid.setContentsMargins(20, 20, 20, 20)
        grid.setSpacing(8)

        self.btn_up = self._make_dir_btn("up", "teleopBtnUp")
        self.btn_down = self._make_dir_btn("down", "teleopBtnDown")
        self.btn_left = self._make_dir_btn("left", "teleopBtnLeft")
        self.btn_right = self._make_dir_btn("right", "teleopBtnRight")
        self.btn_stop = self._make_stop_btn()

        grid.addWidget(self.btn_up, 0, 1)
        grid.addWidget(self.btn_left, 1, 0)
        grid.addWidget(self.btn_stop, 1, 1)
        grid.addWidget(self.btn_right, 1, 2)
        grid.addWidget(self.btn_down, 2, 1)

        for c in range(3):
            grid.setColumnStretch(c, 1)
        for r in range(3):
            grid.setRowStretch(r, 1)

    def _make_dir_btn(self, kind: str, obj_name: str) -> QPushButton:
        btn = QPushButton(_GLYPH[kind], self)
        btn.setObjectName(obj_name)
        btn.setProperty("dpadKind", kind)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
        f = QFont(btn.font())
        f.setPointSize(18)
        f.setBold(True)
        btn.setFont(f)
        btn.setStyleSheet(self._dir_btn_style())
        return btn

    def _make_stop_btn(self) -> QPushButton:
        btn = QPushButton("STOP", self)
        btn.setObjectName("teleopBtnStop")
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
        f = QFont(btn.font())
        f.setPointSize(11)
        f.setBold(True)
        f.setLetterSpacing(QFont.PercentageSpacing, 110)
        btn.setFont(f)
        btn.setStyleSheet(self._stop_btn_style())
        return btn

    @staticmethod
    def _dir_btn_style() -> str:
        idle_bg = COLORS["panel"]
        idle_border = COLORS["border_strong"]
        idle_text = COLORS["text_soft"]
        hover_bg = soften(COLORS["primary"], 0.25)
        active_bg = COLORS["primary"]
        return f"""
            QPushButton {{
                background: {idle_bg};
                color: {idle_text};
                border: 2px solid {idle_border};
                border-radius: 18px;
            }}
            QPushButton:hover {{
                background: {hover_bg};
                border-color: {COLORS["primary"]};
                color: {COLORS["text"]};
            }}
            QPushButton:pressed {{
                background: {active_bg};
                color: white;
                border-color: {active_bg};
            }}
        """

    @staticmethod
    def _stop_btn_style() -> str:
        bg = COLORS["panel"]
        return f"""
            QPushButton {{
                background: {bg};
                color: {COLORS["danger"]};
                border: 2px solid {soften(COLORS["danger"], 0.4)};
                border-radius: 30px;
                padding: 0;
            }}
            QPushButton:hover {{
                background: {soften(COLORS["danger"], 0.18)};
                border-color: {COLORS["danger"]};
            }}
            QPushButton:pressed {{
                background: {COLORS["danger"]};
                color: white;
                border-color: {COLORS["danger"]};
            }}
        """

    def set_active(self, active: set[str]) -> None:
        if active == self._active:
            return
        self._active = set(active)
        self.update()

    def paintEvent(self, _evt) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # 외곽 라운드 패드
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        outer = QPainterPath()
        outer.addRoundedRect(rect, 26, 26)
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0, QColor(COLORS["bg_alt"]))
        grad.setColorAt(1, QColor(soften(COLORS["primary_dim"], 0.55)))
        p.fillPath(outer, grad)
        p.setPen(QPen(QColor(COLORS["border_strong"]), 1.4))
        p.drawPath(outer)

        # 가운데 디스크 (조이스틱 베이스)
        cx, cy = rect.center().x(), rect.center().y()
        disk_r = min(rect.width(), rect.height()) * 0.36
        disk_grad = QRadialGradient(QPointF(cx, cy), disk_r)
        disk_grad.setColorAt(0, QColor(COLORS["panel"]))
        disk_grad.setColorAt(1, QColor(COLORS["bg_alt"]))
        p.setBrush(disk_grad)
        p.setPen(QPen(QColor(COLORS["border_strong"]), 1))
        p.drawEllipse(QPointF(cx, cy), disk_r, disk_r)

        # 활성 방향 빛 — 현재 누른 방향 살짝 빛남
        for kind in self._active:
            off = {"up": (0, -1), "down": (0, 1),
                   "left": (-1, 0), "right": (1, 0)}[kind]
            tx = cx + off[0] * disk_r * 0.85
            ty = cy + off[1] * disk_r * 0.85
            glow = QRadialGradient(QPointF(tx, ty), 26)
            glow.setColorAt(0, QColor(255, 143, 171, 180))
            glow.setColorAt(1, QColor(255, 143, 171, 0))
            p.setBrush(glow)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(tx, ty), 26, 26)


# --------------------------------------------------------------------------
# LiveReadout — 큰 현재 명령 표시 + 능동 방향 chevron 라이트
# --------------------------------------------------------------------------


class LiveReadout(QFrame):
    """우측 cockpit 의 큰 readout. cmd_row 와 동일 역할."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("teleopCmdRow")
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet(
            f"""
            #teleopCmdRow {{
                background: {COLORS["panel"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 14px;
            }}
            """
        )
        self._lin = 0.0
        self._ang = 0.0
        self._active: set[str] = set()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(4)

        cap = QLabel("CURRENT")
        cap.setStyleSheet(
            f"color: {COLORS['text_muted']}; "
            f"font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1.6px;"
        )
        lay.addWidget(cap)

        self._values = QLabel("0.00 m/s   ·   0.00 rad/s")
        f = QFont(self._values.font())
        f.setPointSize(20)
        f.setWeight(QFont.DemiBold)
        f.setStyleHint(QFont.TypeWriter)
        self._values.setFont(f)
        self._values.setStyleSheet(f"color: {COLORS['text']};")
        lay.addWidget(self._values)

        self._sub = QLabel("입력 없음")
        self._sub.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; "
            f"font-weight: 600; letter-spacing: 0.5px;"
        )
        lay.addWidget(self._sub)

        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_value(self, raw: str) -> None:
        """cmd_row.set_value 호환 — 'lin / ang' 형태 또는 ws raw 텍스트."""
        try:
            parts = raw.replace(" ", "").split("/")
            lin = float(parts[0])
            ang = float(parts[1])
        except (ValueError, IndexError):
            self._values.setText(raw)
            return
        self.set_cmd(lin, ang)

    def set_cmd(self, lin: float, ang: float) -> None:
        self._lin = lin
        self._ang = ang
        self._values.setText(f"{lin:+.2f} m/s   ·   {ang:+.2f} rad/s")
        active = abs(lin) > 1e-3 or abs(ang) > 1e-3
        if active:
            self._sub.setText("주행 중 — 손을 떼면 즉시 정지")
            self._sub.setStyleSheet(
                f"color: {COLORS['primary']}; font-size: 11px; "
                f"font-weight: 700; letter-spacing: 0.5px;"
            )
        else:
            self._sub.setText("입력 없음")
            self._sub.setStyleSheet(
                f"color: {COLORS['text_muted']}; font-size: 11px; "
                f"font-weight: 600; letter-spacing: 0.5px;"
            )
        self.update()

    def set_active(self, active: set[str]) -> None:
        if active == self._active:
            return
        self._active = set(active)
        self.update()

    def paintEvent(self, evt) -> None:  # noqa: N802
        super().paintEvent(evt)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 우측 가장자리에 능동 방향 chevron 4개
        rect = self.rect()
        right = rect.right() - 14
        cy = rect.center().y()
        gap = 18
        positions = {
            "up":    (right, cy - gap * 1.3),
            "down":  (right, cy + gap * 1.3),
            "left":  (right - gap * 1.3, cy),
            "right": (right + gap * 0.0, cy),
        }
        # left/right chevron 은 같은 라인에 배치하기 어려우니, 단순화:
        # 위/아래 chevron 만 표시 (linear 방향), angular 는 readout 텍스트에 부호로 표현.
        pos_up = QPointF(right, cy - 16)
        pos_down = QPointF(right, cy + 16)
        self._draw_chevron(p, pos_up, up=True, on=("up" in self._active))
        self._draw_chevron(p, pos_down, up=False, on=("down" in self._active))

    def _draw_chevron(self, p: QPainter, c: QPointF, up: bool, on: bool) -> None:
        col = QColor(COLORS["primary"]) if on else QColor(COLORS["border_strong"])
        pen = QPen(col, 2.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        size = 7
        if up:
            p.drawLine(c + QPointF(-size, size * 0.5),
                       c + QPointF(0, -size * 0.5))
            p.drawLine(c + QPointF(0, -size * 0.5),
                       c + QPointF(size, size * 0.5))
        else:
            p.drawLine(c + QPointF(-size, -size * 0.5),
                       c + QPointF(0, size * 0.5))
            p.drawLine(c + QPointF(0, size * 0.5),
                       c + QPointF(size, -size * 0.5))


# --------------------------------------------------------------------------
# OdomMini — 작은 2D 좌표 + heading
# --------------------------------------------------------------------------


class OdomMini(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("teleopOdomMini")
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self._x = 0.0
        self._y = 0.0
        self._yaw = 0.0
        self._has = False

    def set_odom(self, x: float, y: float, yaw: float) -> None:
        self._x, self._y, self._yaw = x, y, yaw
        self._has = True
        self.update()

    def paintEvent(self, _evt) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        # 라운드 배경 + 옅은 그라데이션
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        bg = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg.setColorAt(0, QColor(COLORS["bg_alt"]))
        bg.setColorAt(1, QColor(soften(COLORS["sky"], 0.5)))
        p.fillPath(path, bg)
        p.setPen(QPen(QColor(COLORS["border"]), 1))
        p.drawPath(path)

        cx, cy = rect.center().x(), rect.center().y()

        # 헤더
        f = QFont(self.font())
        f.setPointSize(9)
        f.setBold(True)
        f.setLetterSpacing(QFont.PercentageSpacing, 130)
        p.setFont(f)
        p.setPen(QColor(COLORS["text_muted"]))
        p.drawText(QRectF(rect.left() + 12, rect.top() + 6, 80, 14),
                   Qt.AlignVCenter | Qt.AlignLeft, "ODOM")

        # 그리드
        p.setPen(QPen(QColor(COLORS["border"]), 1, Qt.DotLine))
        for off in (-40, -20, 0, 20, 40):
            p.drawLine(QPointF(cx + off, rect.top() + 22),
                       QPointF(cx + off, rect.bottom() - 6))
            p.drawLine(QPointF(rect.left() + 8, cy + off),
                       QPointF(rect.right() - 8, cy + off))

        # 중심 십자
        p.setPen(QPen(QColor(COLORS["border_strong"]), 1.2))
        p.drawLine(QPointF(cx - 6, cy), QPointF(cx + 6, cy))
        p.drawLine(QPointF(cx, cy - 6), QPointF(cx, cy + 6))

        if not self._has:
            f.setLetterSpacing(QFont.PercentageSpacing, 100)
            f.setPointSize(10)
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor(COLORS["text_muted"]))
            p.drawText(rect.adjusted(0, 18, 0, 0), Qt.AlignCenter, "데이터 없음")
            return

        # 로봇 위치 (중앙 고정) + heading 화살표
        arrow_len = 32
        ax = cx + arrow_len * math.cos(self._yaw)
        ay = cy - arrow_len * math.sin(self._yaw)
        # 화살표 line
        pen = QPen(QColor(COLORS["primary"]), 3)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(cx, cy), QPointF(ax, ay))
        # 화살촉
        head_l = 8
        ang = self._yaw
        p.setBrush(QColor(COLORS["primary"]))
        p.setPen(Qt.NoPen)
        from PyQt5.QtGui import QPolygonF
        head = QPolygonF([
            QPointF(ax, ay),
            QPointF(ax - head_l * math.cos(ang - 0.5),
                    ay + head_l * math.sin(ang - 0.5)),
            QPointF(ax - head_l * math.cos(ang + 0.5),
                    ay + head_l * math.sin(ang + 0.5)),
        ])
        p.drawPolygon(head)
        # 중심 점
        p.setBrush(QColor(COLORS["panel"]))
        p.setPen(QPen(QColor(COLORS["primary"]), 2))
        p.drawEllipse(QPointF(cx, cy), 5.0, 5.0)

        # 좌표 라벨
        f.setLetterSpacing(QFont.PercentageSpacing, 100)
        f.setPointSize(9)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(COLORS["text_soft"]))
        coord = f"x {self._x:+.2f}  y {self._y:+.2f}"
        p.drawText(QRectF(rect.left() + 12, rect.bottom() - 22,
                          rect.width() - 24, 16),
                   Qt.AlignVCenter | Qt.AlignLeft, coord)


# --------------------------------------------------------------------------
# ScanMini — LiDAR polar plot + range rings
# --------------------------------------------------------------------------


class ScanMini(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("teleopScanMini")
        self.setMinimumHeight(110)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self._ranges: list[float] = []
        self._angle_min = 0.0
        self._angle_inc = 0.0

    def set_scan(self, angle_min: float, angle_inc: float,
                 ranges: list[float]) -> None:
        self._angle_min = angle_min
        self._angle_inc = angle_inc
        self._ranges = list(ranges)
        self.update()

    def paintEvent(self, _evt) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        # 라운드 배경
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        bg = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg.setColorAt(0, QColor(COLORS["bg_alt"]))
        bg.setColorAt(1, QColor(soften(COLORS["mint"], 0.4)))
        p.fillPath(path, bg)
        p.setPen(QPen(QColor(COLORS["border"]), 1))
        p.drawPath(path)

        # 헤더
        f = QFont(self.font())
        f.setPointSize(9)
        f.setBold(True)
        f.setLetterSpacing(QFont.PercentageSpacing, 130)
        p.setFont(f)
        p.setPen(QColor(COLORS["text_muted"]))
        p.drawText(QRectF(rect.left() + 12, rect.top() + 6, 80, 14),
                   Qt.AlignVCenter | Qt.AlignLeft, "LIDAR")

        cx, cy = rect.center().x(), rect.center().y() + 4
        radius = min(rect.width(), rect.height()) / 2 - 14

        # range rings (1m, 2m, 3m, 4m)
        max_r = 4.0
        p.setPen(QPen(QColor(COLORS["border"]), 1, Qt.DotLine))
        for ring in (1.0, 2.0, 3.0, 4.0):
            rr = radius * ring / max_r
            p.drawEllipse(QPointF(cx, cy), rr, rr)
        # 외곽 진한 링
        p.setPen(QPen(QColor(COLORS["border_strong"]), 1.2))
        p.drawEllipse(QPointF(cx, cy), radius, radius)
        # 십자 축
        p.setPen(QPen(QColor(COLORS["border"]), 1))
        p.drawLine(QPointF(cx - radius, cy), QPointF(cx + radius, cy))
        p.drawLine(QPointF(cx, cy - radius), QPointF(cx, cy + radius))

        if not self._ranges:
            ff = QFont(self.font())
            ff.setPointSize(10)
            p.setFont(ff)
            p.setPen(QColor(COLORS["text_muted"]))
            p.drawText(rect.adjusted(0, 22, 0, 0), Qt.AlignCenter, "데이터 없음")
            return

        # 점들
        col = QColor(COLORS["sky"])
        col.setAlpha(220)
        pen = QPen(col, 2.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        for i, r in enumerate(self._ranges):
            if not math.isfinite(r) or r <= 0:
                continue
            r_clip = min(r, max_r)
            theta = self._angle_min + i * self._angle_inc
            px = cx + (r_clip / max_r) * radius * math.cos(theta)
            py = cy - (r_clip / max_r) * radius * math.sin(theta)
            p.drawPoint(QPointF(px, py))

        # 로봇 표시 (중앙 점)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(COLORS["primary"]))
        p.drawEllipse(QPointF(cx, cy), 4, 4)


# --------------------------------------------------------------------------
# TeleopCard
# --------------------------------------------------------------------------


class TeleopCard(QWidget):
    """디버깅용 GogoPing 직접 조작 카드."""

    DEFAULT_VIC_IPS_JSON = (
        pathlib.Path(__file__).resolve().parents[3] / "shared" / "machine_ips.json"
    )

    def __init__(
        self,
        send_cmd_vel: SendCmdFn,
        get_health: Callable[[], dict | None] | None = None,
        machine_ips_json: pathlib.Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("teleopCard")
        self.setFocusPolicy(Qt.StrongFocus)

        self._send = send_cmd_vel
        self._get_health = get_health
        self._ips_json = machine_ips_json or self.DEFAULT_VIC_IPS_JSON

        self._keys_down: set[int] = set()
        self._buttons_down: set[str] = set()
        self._publishing = False
        self._last_sent_zero = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._card = Card("Teleop · 직접 조작")
        outer.addWidget(self._card)

        body = self._card.body

        # ---------- 헤더: 통신 상태 + IP ----------
        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        self.comm_badge = StatusBadge("연결 대기", COLORS["text_muted"])
        self.comm_badge.setObjectName("teleopCommBadge")
        head_row.addWidget(self.comm_badge)
        head_row.addStretch(1)
        self.ip_label = QLabel(f"vic · {_load_vic_ip(self._ips_json)}")
        self.ip_label.setObjectName("teleopIpLabel")
        self.ip_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; "
            f"font-size: 11px; font-weight: 600; "
            f"letter-spacing: 0.6px;"
        )
        head_row.addWidget(self.ip_label)
        body.addLayout(head_row)

        # ---------- 단일 가로 행: D-pad | Cockpit | Telemetry stack ----------
        # 세로 공간을 아끼고, 가로 빈 공간을 ODOM/LIDAR 가 흡수한다.
        main_row = QHBoxLayout()
        main_row.setSpacing(14)

        # ── D-pad (왼쪽 컬럼) ──
        self._pad = DirectionalPad(self)
        # 호환: 외부에서 self.btn_up 등 직접 접근 가능하도록 재노출
        self.btn_up = self._pad.btn_up
        self.btn_down = self._pad.btn_down
        self.btn_left = self._pad.btn_left
        self.btn_right = self._pad.btn_right
        self.btn_stop = self._pad.btn_stop

        self.btn_up.pressed.connect(lambda: self._on_btn_pressed("up"))
        self.btn_up.released.connect(lambda: self._on_btn_released("up"))
        self.btn_down.pressed.connect(lambda: self._on_btn_pressed("down"))
        self.btn_down.released.connect(lambda: self._on_btn_released("down"))
        self.btn_left.pressed.connect(lambda: self._on_btn_pressed("left"))
        self.btn_left.released.connect(lambda: self._on_btn_released("left"))
        self.btn_right.pressed.connect(lambda: self._on_btn_pressed("right"))
        self.btn_right.released.connect(lambda: self._on_btn_released("right"))
        self.btn_stop.clicked.connect(self._on_stop_clicked)

        pad_wrap = QVBoxLayout()
        pad_wrap.setContentsMargins(0, 0, 0, 0)
        pad_wrap.setSpacing(8)
        pad_wrap.addStretch(1)
        pad_wrap.addWidget(self._pad, 0, Qt.AlignHCenter)
        hint = QLabel("화살표 키 또는 버튼")
        hint.setAlignment(Qt.AlignHCenter)
        hint.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; font-weight: 600;"
        )
        pad_wrap.addWidget(hint)
        pad_wrap.addStretch(1)
        main_row.addLayout(pad_wrap, 0)

        # ── Cockpit: live readout + 슬라이더 (가운데 컬럼) ──
        cockpit = QVBoxLayout()
        cockpit.setSpacing(10)
        self.cmd_row = LiveReadout(self)
        cockpit.addWidget(self.cmd_row, 0)
        cockpit.addWidget(self._build_sliders(), 0)
        cockpit.addStretch(1)
        main_row.addLayout(cockpit, 3)

        # ── Telemetry: ODOM 위 / LIDAR 아래 (오른쪽 컬럼) ──
        self.odom_view = OdomMini(self)
        self.scan_view = ScanMini(self)
        tele_stack = QVBoxLayout()
        tele_stack.setSpacing(10)
        tele_stack.addWidget(self.odom_view, 1)
        tele_stack.addWidget(self.scan_view, 1)
        main_row.addLayout(tele_stack, 2)

        body.addLayout(main_row)

        # 송신 / health 타이머
        self._cmd_timer = QTimer(self)
        self._cmd_timer.setInterval(CMD_TICK_MS)
        self._cmd_timer.timeout.connect(self._on_cmd_tick)

        self._health_timer = QTimer(self)
        self._health_timer.setInterval(HEALTH_TICK_MS)
        self._health_timer.timeout.connect(self._on_health_tick)
        self._health_timer.start()

    # --------------------------------------------------------------- build

    def _build_sliders(self) -> QWidget:
        box = QFrame()
        box.setObjectName("teleopSliderBox")
        box.setStyleSheet(
            f"""
            #teleopSliderBox {{
                background: {COLORS["panel"]};
                border: 1px solid {COLORS["border"]};
                border-radius: 14px;
            }}
            QSlider::groove:horizontal {{
                background: {COLORS["track"]};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {COLORS["primary"]};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {COLORS["panel"]};
                border: 2px solid {COLORS["primary"]};
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 8px;
            }}
            """
        )
        lay = QGridLayout(box)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setHorizontalSpacing(12)
        lay.setVerticalSpacing(8)

        def _label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {COLORS['text_soft']}; "
                f"font-size: 11px; font-weight: 700; "
                f"letter-spacing: 1.0px;"
            )
            return lbl

        def _value_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setMinimumWidth(78)
            lbl.setStyleSheet(
                f"color: {COLORS['text']}; "
                f"font-size: 12px; font-weight: 700;"
            )
            return lbl

        lay.addWidget(_label("선속도 LIN"), 0, 0)
        self.linear_slider = QSlider(Qt.Horizontal, box)
        self.linear_slider.setObjectName("teleopLinearSlider")
        self.linear_slider.setMinimum(0)
        self.linear_slider.setMaximum(50)
        self.linear_slider.setValue(20)
        self.linear_slider.setFocusPolicy(Qt.NoFocus)
        self.linear_value = _value_label("0.20 m/s")
        self.linear_slider.valueChanged.connect(
            lambda v: self.linear_value.setText(f"{v / 100:.2f} m/s")
        )
        lay.addWidget(self.linear_slider, 0, 1)
        lay.addWidget(self.linear_value, 0, 2)

        lay.addWidget(_label("각속도 ANG"), 1, 0)
        self.angular_slider = QSlider(Qt.Horizontal, box)
        self.angular_slider.setObjectName("teleopAngularSlider")
        self.angular_slider.setMinimum(0)
        self.angular_slider.setMaximum(150)
        self.angular_slider.setValue(60)
        self.angular_slider.setFocusPolicy(Qt.NoFocus)
        self.angular_value = _value_label("0.60 rad/s")
        self.angular_slider.valueChanged.connect(
            lambda v: self.angular_value.setText(f"{v / 100:.2f} rad/s")
        )
        lay.addWidget(self.angular_slider, 1, 1)
        lay.addWidget(self.angular_value, 1, 2)

        lay.setColumnStretch(1, 1)
        return box

    # ---------------------------------------------------- 입력 처리

    def _btn_for_kind(self, kind: str) -> QPushButton:
        return {"up": self.btn_up, "down": self.btn_down,
                "left": self.btn_left, "right": self.btn_right}[kind]

    def _on_btn_pressed(self, kind: str) -> None:
        self._buttons_down.add(kind)
        self._sync_active_indicators()
        self._ensure_publishing()

    def _on_btn_released(self, kind: str) -> None:
        self._buttons_down.discard(kind)
        self._sync_active_indicators()
        self._maybe_stop()

    def _on_stop_clicked(self) -> None:
        self._buttons_down.clear()
        self._keys_down.clear()
        self._publishing = False
        self._cmd_timer.stop()
        self._send_zero_once()
        # 키 입력으로 setDown 시켰던 버튼들 모두 시각 해제
        for kind in ("up", "down", "left", "right"):
            self._btn_for_kind(kind).setDown(False)
        self._sync_active_indicators()

    def _active_directions(self) -> set[str]:
        active = set(self._buttons_down)
        for key, kind in _KEY_TO_KIND.items():
            if key in self._keys_down:
                active.add(kind)
        return active

    def _sync_active_indicators(self) -> None:
        active = self._active_directions()
        self._pad.set_active(active)
        self.cmd_row.set_active(active)

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.isAutoRepeat():
            return
        k = e.key()
        if k == Qt.Key_Space:
            self._on_stop_clicked()
            return
        kind = _KEY_TO_KIND.get(k)
        if kind is not None:
            self._keys_down.add(k)
            # QSS :pressed 트리거하여 마우스 클릭과 동일한 시각 피드백
            self._btn_for_kind(kind).setDown(True)
            self._sync_active_indicators()
            self._ensure_publishing()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e) -> None:  # noqa: N802
        if e.isAutoRepeat():
            return
        k = e.key()
        if k in self._keys_down:
            self._keys_down.discard(k)
            kind = _KEY_TO_KIND.get(k)
            if kind is not None:
                self._btn_for_kind(kind).setDown(False)
            self._sync_active_indicators()
            self._maybe_stop()
            return
        super().keyReleaseEvent(e)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.setFocus()

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self._on_stop_clicked()
        super().focusOutEvent(e)

    # --------------------------------------------------- publish loop

    def _ensure_publishing(self) -> None:
        if not self._publishing:
            self._publishing = True
            self._last_sent_zero = False
            self._cmd_timer.start()
            self._on_cmd_tick()

    def _maybe_stop(self) -> None:
        if self._keys_down or self._buttons_down:
            return
        self._publishing = False
        self._cmd_timer.stop()
        self._send_zero_once()

    def _send_zero_once(self) -> None:
        self._send(0.0, 0.0)
        self.cmd_row.set_cmd(0.0, 0.0)
        self._last_sent_zero = True

    def _compute_cmd(self) -> tuple[float, float]:
        lin = 0.0
        ang = 0.0
        l_scale = self.linear_slider.value() / 100.0
        a_scale = self.angular_slider.value() / 100.0
        if Qt.Key_Up in self._keys_down or "up" in self._buttons_down:
            lin += l_scale
        if Qt.Key_Down in self._keys_down or "down" in self._buttons_down:
            lin -= l_scale
        if Qt.Key_Left in self._keys_down or "left" in self._buttons_down:
            ang += a_scale
        if Qt.Key_Right in self._keys_down or "right" in self._buttons_down:
            ang -= a_scale
        return lin, ang

    def _on_cmd_tick(self) -> None:
        lin, ang = self._compute_cmd()
        self._send(lin, ang)
        self.cmd_row.set_cmd(lin, ang)

    # --------------------------------------------------- state in (WS)

    def on_state(self, msg: dict) -> None:
        odom = msg.get("odom")
        if odom:
            self.odom_view.set_odom(
                float(odom.get("x", 0.0)),
                float(odom.get("y", 0.0)),
                float(odom.get("yaw", 0.0)),
            )
        scan = msg.get("scan")
        if scan and scan.get("ranges"):
            self.scan_view.set_scan(
                float(scan.get("angle_min", 0.0)),
                float(scan.get("angle_inc", 0.0)),
                list(scan.get("ranges", [])),
            )
        ros_ok = bool(msg.get("ros_ok", False))
        self._set_comm_badge(ros_ok)

    def on_disconnect(self) -> None:
        self._set_comm_badge(False, label="통신 끊김")

    def _set_comm_badge(self, ok: bool, label: str | None = None) -> None:
        if ok:
            self.comm_badge.set_status(label or "정상", COLORS["success"])
        else:
            self.comm_badge.set_status(label or "연결 대기", COLORS["danger"])

    # --------------------------------------------------- health

    def _on_health_tick(self) -> None:
        if self._get_health is None:
            return
        info = self._get_health()
        if info is None:
            self._set_comm_badge(False, label="통신 끊김")
            return
        self._set_comm_badge(bool(info.get("ros_ok", False)))
