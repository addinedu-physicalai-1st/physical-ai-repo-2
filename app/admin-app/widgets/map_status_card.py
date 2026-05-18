"""Map Status card — 현재 로봇 좌표 + 맵 안/밖 인디케이터.

GogoPingDashboard 의 ODOM 카드 옆에 배치. snapshot 의 in_map / robot_pose 받아
배지 + 좌표 표시. **디버그 좌표 override 는 별도 위젯** (PoseDebugPanel — TopBar
BTStateInline 의 배터리 디버그 옆에 배치).

| in_map | 표시 |
|---|---|
| True   | 🟢 IN MAP (success) |
| False  | 🔴 OUT OF MAP (danger) |
| None   | ⚪ UNKNOWN (맵 미수신 또는 odom 미수신) |
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from theme import COLORS

from . import soften


class MapStatusCard(QWidget):
    """🟢/🔴/⚪ 배지 + 좌표 라벨 (compact)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mapStatusCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(2)

        # 배지 (icon + 라벨 한 줄)
        self._icon = QLabel("⚪")
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setStyleSheet("font-size: 13pt; background: transparent;")
        outer.addWidget(self._icon, 0, Qt.AlignCenter)

        self._badge = QLabel("UNKNOWN")
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 8pt; font-weight: 800; "
            f"letter-spacing: 0.6px; background: transparent;"
        )
        outer.addWidget(self._badge, 0, Qt.AlignCenter)

        # 좌표 (x/y/yaw 한 줄씩)
        self._x_label = QLabel("x  —")
        self._y_label = QLabel("y  —")
        self._yaw_label = QLabel("yaw  —")
        for lab in (self._x_label, self._y_label, self._yaw_label):
            lab.setStyleSheet(
                f"color: {COLORS['text']}; font-size: 8pt; font-weight: 700; "
                f"background: transparent;"
            )
            lab.setAlignment(Qt.AlignCenter)
            outer.addWidget(lab, 0, Qt.AlignCenter)

        self.set_status(None)

    # --------------------------------------------------------------- public API

    def set_status(self, in_map: bool | None) -> None:
        """snapshot.in_map (True / False / None) — 배지 갱신."""
        if in_map is True:
            icon, text, accent = "🟢", "IN MAP", COLORS["success"]
        elif in_map is False:
            icon, text, accent = "🔴", "OUT OF MAP", COLORS["danger"]
        else:
            icon, text, accent = "⚪", "UNKNOWN", COLORS["text_muted"]

        self._icon.setText(icon)
        self._badge.setText(text)
        self._badge.setStyleSheet(
            f"color: {accent}; font-size: 8pt; font-weight: 800; "
            f"letter-spacing: 0.6px; background: transparent;"
        )
        bg = soften(accent, 0.12)
        self.setStyleSheet(
            f"""
            QWidget#mapStatusCard {{
                background: {bg};
                border: 1px solid {soften(accent, 0.45)};
                border-radius: 12px;
            }}
            """
        )

    def set_pose(self, pose: dict | None) -> None:
        """snapshot.robot_pose ({x, y, yaw} or None) — 좌표 라벨 갱신."""
        if pose is None:
            self._x_label.setText("x  —")
            self._y_label.setText("y  —")
            self._yaw_label.setText("yaw  —")
            return
        try:
            import math
            x = float(pose.get("x", 0.0))
            y = float(pose.get("y", 0.0))
            yaw_rad = float(pose.get("yaw", 0.0))
            deg = math.degrees(yaw_rad)
        except (TypeError, ValueError):
            return
        self._x_label.setText(f"x  {x:+.2f}")
        self._y_label.setText(f"y  {y:+.2f}")
        self._yaw_label.setText(f"yaw  {deg:+.0f}°")
