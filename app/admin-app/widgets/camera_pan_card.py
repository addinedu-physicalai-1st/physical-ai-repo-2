"""Camera pan/tilt 카드 — 2축 서보 원격 조작 (admin-app).

키/버튼 hold → 10Hz 로 target deg 누적 → Control Server REST POST.
WS 로 servo_bridge 의 실측 JointState 수신해 표시 갱신.
rclpy 직접 import 금지 (Control Server 경유).
"""

from __future__ import annotations

from typing import Callable

from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from theme import COLORS
from widgets import Card, StatusBadge

# 한 tick 당 누적되는 각도 = step_deg / 한 번의 publish 가 한 tick
CMD_TICK_MS = 100  # 10 Hz
HEALTH_TICK_MS = 5000

PAN_MIN, PAN_MAX, PAN_CENTER = 5.0, 175.0, 90.0
TILT_MIN, TILT_MAX, TILT_CENTER = 30.0, 150.0, 90.0

_GLYPH = {"left": "◀", "right": "▶", "up": "▲", "down": "▼"}

# arrow + WASD 모두 지원
_KEY_TO_DIR = {
    Qt.Key_Left: "left", Qt.Key_A: "left",
    Qt.Key_Right: "right", Qt.Key_D: "right",
    Qt.Key_Up: "up", Qt.Key_W: "up",
    Qt.Key_Down: "down", Qt.Key_S: "down",
}

SendCmdFn = Callable[[float | None, float | None], bool]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class CameraPanCard(QWidget):
    """5 버튼 + WASD/arrow + space(center). 누른 동안 step 누적 publish."""

    def __init__(
        self,
        send_cmd: SendCmdFn,
        get_health: Callable[[], dict | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("cameraPanCard")
        self.setFocusPolicy(Qt.StrongFocus)

        self._send = send_cmd
        self._get_health = get_health

        self._keys_down: set[int] = set()
        self._buttons_down: set[str] = set()
        self._publishing = False

        self._target_pan = PAN_CENTER
        self._target_tilt = TILT_CENTER

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._card = Card("Camera Pan/Tilt · 직접 조작")
        outer.addWidget(self._card)
        body = self._card.body

        # ── 헤더: comm 배지 ─────────────────────────────────────────────────
        head = QHBoxLayout()
        head.setSpacing(8)
        self.comm_badge = StatusBadge("연결 대기", COLORS["text_muted"])
        self.comm_badge.setMinimumWidth(80)
        head.addWidget(self.comm_badge)
        head.addStretch(1)
        body.addLayout(head)

        # ── 메인: D-pad | 상태 readout ────────────────────────────────────
        main_row = QHBoxLayout()
        main_row.setSpacing(14)

        main_row.addWidget(self._build_pad(), 0, Qt.AlignVCenter)
        main_row.addWidget(self._build_readout(), 1)

        body.addLayout(main_row)

        # ── 타이머 ────────────────────────────────────────────────────────
        self._cmd_timer = QTimer(self)
        self._cmd_timer.setInterval(CMD_TICK_MS)
        self._cmd_timer.timeout.connect(self._on_cmd_tick)

        self._health_timer = QTimer(self)
        self._health_timer.setInterval(HEALTH_TICK_MS)
        self._health_timer.timeout.connect(self._on_health_tick)
        self._health_timer.start()

    # ── build ────────────────────────────────────────────────────────────────
    def _make_dir_btn(self, kind: str) -> QPushButton:
        btn = QPushButton(_GLYPH[kind], self)
        btn.setObjectName(f"camPanBtn_{kind}")
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setFixedSize(56, 56)
        f = QFont(btn.font())
        f.setPointSize(16)
        f.setBold(True)
        btn.setFont(f)
        btn.pressed.connect(lambda k=kind: self._on_btn_pressed(k))
        btn.released.connect(lambda k=kind: self._on_btn_released(k))
        return btn

    def _build_pad(self) -> QWidget:
        pad = QWidget(self)
        pad.setFixedSize(QSize(200, 200))
        grid = QGridLayout(pad)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(6)

        self.btn_up = self._make_dir_btn("up")
        self.btn_down = self._make_dir_btn("down")
        self.btn_left = self._make_dir_btn("left")
        self.btn_right = self._make_dir_btn("right")

        self.btn_center = QPushButton("●", pad)
        self.btn_center.setObjectName("camPanBtn_center")
        self.btn_center.setFocusPolicy(Qt.NoFocus)
        self.btn_center.setFixedSize(56, 56)
        cf = QFont(self.btn_center.font())
        cf.setPointSize(14)
        cf.setBold(True)
        self.btn_center.setFont(cf)
        self.btn_center.clicked.connect(self._on_center_clicked)

        grid.addWidget(self.btn_up, 0, 1)
        grid.addWidget(self.btn_left, 1, 0)
        grid.addWidget(self.btn_center, 1, 1)
        grid.addWidget(self.btn_right, 1, 2)
        grid.addWidget(self.btn_down, 2, 1)
        return pad

    def _build_readout(self) -> QWidget:
        box = QWidget(self)
        lay = QGridLayout(box)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setHorizontalSpacing(12)
        lay.setVerticalSpacing(8)

        def _hdr(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {COLORS['text_soft']}; "
                f"font-size: 11px; font-weight: 700; letter-spacing: 1.0px;"
            )
            return lbl

        def _val(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color: {COLORS['text']}; font-size: 14px; font-weight: 700;"
            )
            return lbl

        lay.addWidget(_hdr("PAN (실측)"), 0, 0)
        self.pan_value = _val("—")
        lay.addWidget(self.pan_value, 0, 1)
        lay.addWidget(_hdr("TILT (실측)"), 1, 0)
        self.tilt_value = _val("—")
        lay.addWidget(self.tilt_value, 1, 1)

        lay.addWidget(_hdr("PAN target"), 2, 0)
        self.pan_target_lbl = _val(f"{PAN_CENTER:.1f}°")
        lay.addWidget(self.pan_target_lbl, 2, 1)
        lay.addWidget(_hdr("TILT target"), 3, 0)
        self.tilt_target_lbl = _val(f"{TILT_CENTER:.1f}°")
        lay.addWidget(self.tilt_target_lbl, 3, 1)

        lay.addWidget(_hdr("STEP"), 4, 0)
        self.step_spin = QDoubleSpinBox(box)
        self.step_spin.setRange(0.5, 20.0)
        self.step_spin.setSingleStep(0.5)
        self.step_spin.setValue(2.0)
        self.step_spin.setSuffix(" °/tick")
        self.step_spin.setFocusPolicy(Qt.NoFocus)
        self.step_spin.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lay.addWidget(self.step_spin, 4, 1)

        hint = QLabel("키: WASD / 화살표 (hold) · Space=center")
        hint.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px;"
        )
        lay.addWidget(hint, 5, 0, 1, 2)

        lay.setColumnStretch(1, 1)
        return box

    # ── 입력 처리 ────────────────────────────────────────────────────────────
    def _on_btn_pressed(self, kind: str) -> None:
        self._buttons_down.add(kind)
        self._ensure_publishing()

    def _on_btn_released(self, kind: str) -> None:
        self._buttons_down.discard(kind)
        self._maybe_stop()

    def _on_center_clicked(self) -> None:
        self._target_pan = PAN_CENTER
        self._target_tilt = TILT_CENTER
        self._send(self._target_pan, self._target_tilt)
        self._update_target_labels()

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.isAutoRepeat():
            return
        k = e.key()
        if k == Qt.Key_Space:
            self._on_center_clicked()
            return
        if k in _KEY_TO_DIR:
            self._keys_down.add(k)
            self._ensure_publishing()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e) -> None:  # noqa: N802
        if e.isAutoRepeat():
            return
        k = e.key()
        if k in self._keys_down:
            self._keys_down.discard(k)
            self._maybe_stop()
            return
        super().keyReleaseEvent(e)

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        self.setFocus()

    def focusOutEvent(self, e) -> None:  # noqa: N802
        self._buttons_down.clear()
        self._keys_down.clear()
        self._maybe_stop()
        super().focusOutEvent(e)

    # ── 활성 방향 ────────────────────────────────────────────────────────────
    def _active_directions(self) -> set[str]:
        active = set(self._buttons_down)
        for key in self._keys_down:
            d = _KEY_TO_DIR.get(key)
            if d is not None:
                active.add(d)
        return active

    # ── publish loop ─────────────────────────────────────────────────────────
    def _ensure_publishing(self) -> None:
        if not self._publishing:
            self._publishing = True
            self._cmd_timer.start()
            self._on_cmd_tick()

    def _maybe_stop(self) -> None:
        if self._buttons_down or self._keys_down:
            return
        self._publishing = False
        self._cmd_timer.stop()

    def _on_cmd_tick(self) -> None:
        active = self._active_directions()
        if not active:
            return
        step = float(self.step_spin.value())
        pan_changed = tilt_changed = False
        if "left" in active:
            self._target_pan = _clamp(self._target_pan - step, PAN_MIN, PAN_MAX)
            pan_changed = True
        if "right" in active:
            self._target_pan = _clamp(self._target_pan + step, PAN_MIN, PAN_MAX)
            pan_changed = True
        if "up" in active:
            self._target_tilt = _clamp(self._target_tilt + step, TILT_MIN, TILT_MAX)
            tilt_changed = True
        if "down" in active:
            self._target_tilt = _clamp(self._target_tilt - step, TILT_MIN, TILT_MAX)
            tilt_changed = True
        if pan_changed or tilt_changed:
            self._send(
                self._target_pan if pan_changed else None,
                self._target_tilt if tilt_changed else None,
            )
            self._update_target_labels()

    def _update_target_labels(self) -> None:
        self.pan_target_lbl.setText(f"{self._target_pan:.1f}°")
        self.tilt_target_lbl.setText(f"{self._target_tilt:.1f}°")

    # ── WS state in ─────────────────────────────────────────────────────────
    def on_state(self, msg: dict) -> None:
        ros_ok = bool(msg.get("ros_ok", False))
        if ros_ok:
            self.comm_badge.set_status("ROS OK", COLORS["success"])
        else:
            self.comm_badge.set_status("ROS off", COLORS["text_muted"])
        pan = msg.get("pan_deg")
        tilt = msg.get("tilt_deg")
        if pan is not None:
            self.pan_value.setText(f"{float(pan):.1f}°")
        if tilt is not None:
            self.tilt_value.setText(f"{float(tilt):.1f}°")

    # ── health tick ─────────────────────────────────────────────────────────
    def _on_health_tick(self) -> None:
        if self._get_health is None:
            return
        try:
            self._get_health()
        except Exception:
            pass
