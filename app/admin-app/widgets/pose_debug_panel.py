"""[디버그 전용] 로봇 좌표 강제 override panel — BTStateInline 의 디버그 영역.

DebugStatePanel / BatteryDebugSlider 와 같은 노란 dashed border 스타일. x/y/yaw 입력 +
적용 / 원복 버튼. /api/gogoping/debug/pose 호출.

적용: blackboard.ROBOT_POSE 강제 + POSE_OVERRIDE_ACTIVE=True (live amcl_pose 무시)
원복: POSE_OVERRIDE_ACTIVE=False (live amcl_pose 복원)

사용:
    panel = PoseDebugPanel()
    panel.pose_override_requested.connect(
        lambda x, y, yaw, clear: state_client.post_robot_pose(
            x, y, yaw, clear=clear, on_result=panel.set_last_result
        )
    )
"""
from __future__ import annotations

import math

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from theme import COLORS

from . import soften


class PoseDebugPanel(QFrame):
    """x / y / yaw 입력 + 적용 / 원복 버튼."""

    # 적용 / 원복 버튼 클릭 시 emit. 인자: (x, y, yaw, clear)
    pose_override_requested = pyqtSignal(float, float, float, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("poseDebugPanel")
        self.setStyleSheet(
            f"""
            QFrame#poseDebugPanel {{
                background: {soften(COLORS['warning'], 0.30)};
                border: 1px dashed {soften(COLORS['warning'], 0.60)};
                border-radius: 10px;
            }}
            QFrame#poseDebugPanel QLabel {{
                background: transparent;
                color: {COLORS['text_soft']};
                font-size: 8pt;
                font-weight: 700;
            }}
            QDoubleSpinBox {{
                background: {COLORS['panel']};
                border: 1px solid {COLORS['border']};
                border-radius: 5px;
                padding: 2px 6px;
                font-size: 9pt;
                font-weight: 700;
                color: {COLORS['text']};
                min-height: 20px;
            }}
            QPushButton {{
                background: {COLORS['warning']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 8pt;
                font-weight: 800;
                min-height: 22px;
            }}
            QPushButton:hover {{ background: {soften(COLORS['warning'], 0.80)}; }}
            QPushButton#clearBtn {{ background: {COLORS['text_muted']}; }}
            QPushButton#clearBtn:hover {{
                background: {soften(COLORS['text_muted'], 0.80)};
            }}
            """
        )
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.setMinimumWidth(220)
        self.setMaximumWidth(280)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 5, 10, 6)
        outer.setSpacing(3)

        header = QLabel("🎯 POSE")
        header.setStyleSheet(
            f"font-size: 8pt; font-weight: 800; color: {COLORS['text_muted']}; "
            f"letter-spacing: 0.8px; background: transparent;"
        )
        outer.addWidget(header)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(2)
        grid.addWidget(QLabel("x"), 0, 0)
        self._x_input = self._make_spin(-100.0, 100.0, 0.1, suffix=" m")
        grid.addWidget(self._x_input, 0, 1)
        grid.addWidget(QLabel("y"), 1, 0)
        self._y_input = self._make_spin(-100.0, 100.0, 0.1, suffix=" m")
        grid.addWidget(self._y_input, 1, 1)
        grid.addWidget(QLabel("yaw"), 2, 0)
        self._yaw_input = self._make_spin(-180.0, 180.0, 5.0, suffix=" °")
        grid.addWidget(self._yaw_input, 2, 1)
        outer.addLayout(grid)

        btns = QHBoxLayout()
        btns.setContentsMargins(0, 0, 0, 0)
        btns.setSpacing(5)
        self._apply_btn = QPushButton("적용")
        self._apply_btn.setCursor(Qt.PointingHandCursor)
        self._apply_btn.clicked.connect(self._on_apply)
        btns.addWidget(self._apply_btn, 1)
        self._clear_btn = QPushButton("원복")
        self._clear_btn.setObjectName("clearBtn")
        self._clear_btn.setCursor(Qt.PointingHandCursor)
        self._clear_btn.clicked.connect(self._on_clear)
        btns.addWidget(self._clear_btn, 1)
        outer.addLayout(btns)

        self._last_result = QLabel("")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {COLORS['text_soft']}; "
            f"background: transparent;"
        )
        outer.addWidget(self._last_result)

    @staticmethod
    def _make_spin(minv: float, maxv: float, step: float, suffix: str = " m") -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(minv, maxv)
        s.setSingleStep(step)
        s.setDecimals(2)
        s.setSuffix(suffix)
        s.setValue(0.0)
        return s

    # --------------------------------------------------------------- internal

    def _on_apply(self) -> None:
        x = float(self._x_input.value())
        y = float(self._y_input.value())
        yaw_rad = math.radians(self._yaw_input.value())
        self._last_result.setText(f"sending ({x:+.1f}, {y:+.1f}) ...")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {COLORS['text_soft']}; "
            f"background: transparent;"
        )
        self.pose_override_requested.emit(x, y, yaw_rad, False)

    def _on_clear(self) -> None:
        self._last_result.setText("sending clear ...")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {COLORS['text_soft']}; "
            f"background: transparent;"
        )
        self.pose_override_requested.emit(0.0, 0.0, 0.0, True)

    # --------------------------------------------------------------- public

    def set_last_result(self, x: float, y: float, yaw: float, clear: bool, ok: bool, reason: str = "") -> None:
        """state_client 가 POST 응답 받은 후 호출."""
        if clear:
            label = "원복"
        else:
            label = f"({x:+.1f}, {y:+.1f})"
        if ok:
            self._last_result.setText(f"✓ {label}")
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {COLORS['success']}; "
                f"background: transparent;"
            )
        else:
            self._last_result.setText(f"✗ {label}: {reason}")
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {COLORS['danger']}; "
                f"background: transparent;"
            )
