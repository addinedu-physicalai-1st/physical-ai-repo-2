"""디버그 강제 state 전이 컴팩트 카드 — BT SUB 셀 옆.

QComboBox 2개 (state / sub) + "적용" 버튼. state 선택 변경 시 sub 콤보 옵션 자동 갱신.

BT SUB 셀과 같은 카드 스타일로 BTStateInline 의 가로 row 에 자연스럽게 들어감.

사용:
    panel = DebugStatePanel()
    panel.force_state_requested.connect(
        lambda state, sub: state_client.post_force_state(state, sub_task=sub, on_result=panel.set_last_result)
    )
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from theme import COLORS

from . import soften

_STATES = (
    "CHARGING", "IDLE", "ASSIST", "PLAY", "MANUAL",
    "RETURNING", "LOW_BATTERY_RETURN", "ERROR",
)

# state → sub_task options. 빈 문자열 "" = "(none)" 라벨로 표시.
_SUB_OPTIONS: dict[str, tuple[str, ...]] = {
    "CHARGING":            ("",),
    "IDLE":                ("",),
    "ASSIST":              ("", "carry", "follow", "lullaby"),
    "PLAY":                ("", "hideseek"),
    "MANUAL":              ("",),
    "RETURNING":           ("",),
    "LOW_BATTERY_RETURN":  ("",),
    "ERROR":               ("",),
}

_NONE_LABEL = "(none)"


class DebugStatePanel(QFrame):
    """state + sub_task 콤보 + 적용 버튼."""

    # 적용 버튼 클릭 시 emit. 인자: (target_state, sub_task)
    force_state_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("debugStatePanel")
        # BT SUB 셀과 같은 카드 스타일 — 단 디버그 표시로 노란 border
        self.setStyleSheet(
            f"""
            QFrame#debugStatePanel {{
                background: {soften(COLORS['warning'], 0.30)};
                border: 1px dashed {soften(COLORS['warning'], 0.60)};
                border-radius: 10px;
            }}
            QFrame#debugStatePanel QLabel {{ background: transparent; }}
            QComboBox {{
                background: {COLORS['panel']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 2px 6px;
                font-size: 9pt;
                font-weight: 700;
                color: {COLORS['text']};
                min-height: 22px;
            }}
            QPushButton {{
                background: {COLORS['warning']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 9pt;
                font-weight: 800;
                min-height: 24px;
            }}
            QPushButton:hover {{
                background: {soften(COLORS['warning'], 0.80)};
            }}
            QPushButton:pressed {{
                background: {soften(COLORS['warning'], 0.50)};
            }}
            """
        )
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.setMinimumWidth(208)
        self.setMaximumWidth(280)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 5, 10, 6)
        outer.setSpacing(3)

        # 헤더
        header = QLabel("🔧 DEBUG")
        header.setStyleSheet(
            f"font-size: 8pt; font-weight: 800; color: {COLORS['text_muted']}; "
            f"letter-spacing: 0.8px;"
        )
        outer.addWidget(header)

        # 빠른 토글: [수동] [주행] — combo 거치지 않고 즉시 force-state.
        # state row 아래 일반 흐름은 그대로 유지 (정밀 선택용).
        quick_row = QHBoxLayout()
        quick_row.setSpacing(4)
        quick_row.setContentsMargins(0, 0, 0, 0)
        quick_label = QLabel("quick")
        quick_label.setStyleSheet(
            f"font-size: 8pt; color: {COLORS['text_soft']}; min-width: 28px;"
        )
        quick_row.addWidget(quick_label)
        self._quick_manual_btn = QPushButton("수동")
        self._quick_manual_btn.setCursor(Qt.PointingHandCursor)
        self._quick_manual_btn.setStyleSheet(
            f"background: {COLORS['primary']}; color: white; border: none;"
            f" border-radius: 6px; padding: 4px 10px; font-size: 9pt; font-weight: 800;"
            f" min-height: 24px;"
        )
        self._quick_manual_btn.clicked.connect(lambda: self._quick_apply("MANUAL"))
        quick_row.addWidget(self._quick_manual_btn, 1)
        self._quick_drive_btn = QPushButton("주행")
        self._quick_drive_btn.setCursor(Qt.PointingHandCursor)
        self._quick_drive_btn.setStyleSheet(
            f"background: {COLORS['mint']}; color: {COLORS['text']}; border: none;"
            f" border-radius: 6px; padding: 4px 10px; font-size: 9pt; font-weight: 800;"
            f" min-height: 24px;"
        )
        self._quick_drive_btn.clicked.connect(lambda: self._quick_apply("IDLE"))
        quick_row.addWidget(self._quick_drive_btn, 1)
        outer.addLayout(quick_row)

        # state row
        state_row = QHBoxLayout()
        state_row.setSpacing(4)
        state_row.setContentsMargins(0, 0, 0, 0)
        state_label = QLabel("state")
        state_label.setStyleSheet(
            f"font-size: 8pt; color: {COLORS['text_soft']}; min-width: 28px;"
        )
        state_row.addWidget(state_label)
        self._state_combo = QComboBox()
        self._state_combo.addItems(list(_STATES))
        self._state_combo.currentTextChanged.connect(self._on_state_changed)
        state_row.addWidget(self._state_combo, 1)
        outer.addLayout(state_row)

        # sub row + 적용 버튼
        sub_row = QHBoxLayout()
        sub_row.setSpacing(4)
        sub_row.setContentsMargins(0, 0, 0, 0)
        sub_label = QLabel("sub")
        sub_label.setStyleSheet(
            f"font-size: 8pt; color: {COLORS['text_soft']}; min-width: 28px;"
        )
        sub_row.addWidget(sub_label)
        self._sub_combo = QComboBox()
        sub_row.addWidget(self._sub_combo, 1)
        self._apply_btn = QPushButton("적용")
        self._apply_btn.setCursor(Qt.PointingHandCursor)
        self._apply_btn.clicked.connect(self._on_apply)
        sub_row.addWidget(self._apply_btn, 0)
        outer.addLayout(sub_row)

        # 마지막 결과 표시 (한 줄)
        self._last_result = QLabel("")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {COLORS['text_soft']};"
        )
        outer.addWidget(self._last_result)

        # 초기 sub combo 옵션 채움
        self._refresh_sub_options(self._state_combo.currentText())

    # --------------------------------------------------------------- internal

    def _on_state_changed(self, state: str) -> None:
        self._refresh_sub_options(state)

    def _refresh_sub_options(self, state: str) -> None:
        self._sub_combo.blockSignals(True)
        self._sub_combo.clear()
        for opt in _SUB_OPTIONS.get(state, ("",)):
            self._sub_combo.addItem(_NONE_LABEL if opt == "" else opt, opt)
        self._sub_combo.blockSignals(False)

    def _on_apply(self) -> None:
        state = self._state_combo.currentText()
        # currentData() 가 actual sub_task 값 ("" / "carry" / "follow" / ...)
        sub_task = self._sub_combo.currentData() or ""
        self._last_result.setText(f"sending → {state} / {sub_task or _NONE_LABEL} ...")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {COLORS['text_soft']};"
        )
        self.force_state_requested.emit(state, sub_task)

    def _quick_apply(self, state: str) -> None:
        """수동/주행 빠른 토글 — sub_task 없이 즉시 force-state. combo 동기화 안 함."""
        self._last_result.setText(f"sending → {state} (quick) ...")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {COLORS['text_soft']};"
        )
        self.force_state_requested.emit(state, "")

    # --------------------------------------------------------------- public

    def set_last_result(self, state: str, ok: bool, reason: str = "") -> None:
        """state_client 가 POST 응답 받은 후 호출."""
        if ok:
            self._last_result.setText(f"✓ {state}")
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {COLORS['success']};"
            )
        else:
            self._last_result.setText(f"✗ {state}: {reason}")
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {COLORS['danger']};"
            )
