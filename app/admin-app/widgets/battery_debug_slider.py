"""[sim 디버그 전용] 배터리 레벨 슬라이더 — BT SUB 셀 옆.

QSlider(0~100) + 현재값 라벨 + 적용 버튼. ``DebugStatePanel`` 과 같은 카드 스타일 (노란
dashed border) — 둘 다 디버그 표시.

운영(실물 Pi) 환경에선 server (sim_battery_node) 없음 → ``service_unavailable`` 응답
받아 ✗ 표시.

사용:
    slider = BatteryDebugSlider()
    slider.battery_level_requested.connect(
        lambda level: state_client.post_battery_level(level, on_result=slider.set_last_result)
    )
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
)

from theme import COLORS

from . import soften


_LOW_ENTER = 20.0   # battery_low_monitor 임계 — 슬라이더에 표시
_LOW_EXIT = 25.0
_FULL_ENTER = 70.0  # battery_full_monitor 임계


class BatteryDebugSlider(QFrame):
    """배터리 레벨 슬라이더 + 적용 버튼."""

    # 적용 버튼 클릭 시 emit. 인자: level (float, 0.0~100.0)
    battery_level_requested = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("batteryDebugSlider")
        # DebugStatePanel 과 같은 노란 dashed border (디버그 표식)
        self.setStyleSheet(
            f"""
            QFrame#batteryDebugSlider {{
                background: {soften(COLORS['warning'], 0.30)};
                border: 1px dashed {soften(COLORS['warning'], 0.60)};
                border-radius: 10px;
            }}
            QFrame#batteryDebugSlider QLabel {{ background: transparent; }}
            QSlider::groove:horizontal {{
                height: 6px;
                background: {COLORS['border']};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {COLORS['warning']};
                width: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {soften(COLORS['warning'], 0.60)};
                border-radius: 3px;
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
        self.setMinimumWidth(228)
        self.setMaximumWidth(300)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 5, 10, 6)
        outer.setSpacing(3)

        # 헤더
        header = QLabel("🔋 BATTERY")
        header.setStyleSheet(
            f"font-size: 8pt; font-weight: 800; color: {COLORS['text_muted']}; "
            f"letter-spacing: 0.8px;"
        )
        outer.addWidget(header)

        # slider row
        slider_row = QHBoxLayout()
        slider_row.setSpacing(6)
        slider_row.setContentsMargins(0, 0, 0, 0)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, 100)
        self._slider.setValue(100)
        self._slider.setMinimumWidth(110)
        self._slider.valueChanged.connect(self._on_value_changed)
        slider_row.addWidget(self._slider, 1)
        self._value_label = QLabel("100%")
        self._value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value_label.setStyleSheet(
            f"font-size: 9pt; font-weight: 800; color: {COLORS['text']}; min-width: 36px;"
        )
        slider_row.addWidget(self._value_label, 0)
        outer.addLayout(slider_row)

        # 적용 버튼 + 임계점 안내 + 결과
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        bottom.setContentsMargins(0, 0, 0, 0)

        thresholds = QLabel(
            f"<span style='color: {COLORS['text_soft']};'>low&nbsp;{int(_LOW_ENTER)}/{int(_LOW_EXIT)}&nbsp;&nbsp;full&nbsp;{int(_FULL_ENTER)}</span>"
        )
        thresholds.setStyleSheet(f"font-size: 8pt;")
        bottom.addWidget(thresholds, 1)

        self._apply_btn = QPushButton("적용")
        self._apply_btn.setCursor(Qt.PointingHandCursor)
        self._apply_btn.clicked.connect(self._on_apply)
        bottom.addWidget(self._apply_btn, 0)
        outer.addLayout(bottom)

        # 마지막 결과 (한 줄)
        self._last_result = QLabel("")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {COLORS['text_soft']};"
        )
        outer.addWidget(self._last_result)

    # --------------------------------------------------------------- internal

    def _on_value_changed(self, value: int) -> None:
        self._value_label.setText(f"{value}%")

    def _on_apply(self) -> None:
        level = float(self._slider.value())
        self._last_result.setText(f"sending → {level:.0f}% ...")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {COLORS['text_soft']};"
        )
        self.battery_level_requested.emit(level)

    # --------------------------------------------------------------- public

    def set_last_result(self, level: float, ok: bool, reason: str = "") -> None:
        """state_client 가 POST 응답 받은 후 호출."""
        if ok:
            self._last_result.setText(f"✓ {level:.0f}%")
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {COLORS['success']};"
            )
        else:
            self._last_result.setText(f"✗ {level:.0f}%: {reason}")
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {COLORS['danger']};"
            )
