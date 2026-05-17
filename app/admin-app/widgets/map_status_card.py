"""Map Status card — 현재 로봇 좌표가 맵 안인지 밖인지 시각화.

GogoPingDashboard 의 ODOM 카드 옆에 배치 — 같은 가로 행. snapshot.in_map 값
(True/False/None) 을 받아 색상 + 라벨 표시.

| in_map | 표시 |
|---|---|
| True   | 🟢 IN MAP (success) |
| False  | 🔴 OUT OF MAP (danger) |
| None   | ⚪ UNKNOWN (맵 미수신 또는 odom 미수신) |

좌표 자체는 별도 widget (OdomCompact) 가 이미 표시함 — 본 card 는 boolean 상태만.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from theme import COLORS

from . import soften


class MapStatusCard(QWidget):
    """🟢 IN MAP / 🔴 OUT OF MAP / ⚪ UNKNOWN 배지."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mapStatusCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(4)

        self._icon = QLabel("⚪")
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setStyleSheet("font-size: 28pt; background: transparent;")
        outer.addWidget(self._icon, 0, Qt.AlignCenter)

        self._label = QLabel("UNKNOWN")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11pt; font-weight: 800; "
            f"letter-spacing: 0.8px; background: transparent;"
        )
        outer.addWidget(self._label, 0, Qt.AlignCenter)

        self.set_status(None)

    def set_status(self, in_map: bool | None) -> None:
        """snapshot.in_map (True / False / None) 받아 표시 갱신."""
        if in_map is True:
            icon, text, accent = "🟢", "IN MAP", COLORS["success"]
        elif in_map is False:
            icon, text, accent = "🔴", "OUT OF MAP", COLORS["danger"]
        else:
            icon, text, accent = "⚪", "UNKNOWN", COLORS["text_muted"]

        self._icon.setText(icon)
        self._label.setText(text)
        self._label.setStyleSheet(
            f"color: {accent}; font-size: 11pt; font-weight: 800; "
            f"letter-spacing: 0.8px; background: transparent;"
        )
        # 카드 자체에도 옅은 톤
        bg = soften(accent, 0.15)
        self.setStyleSheet(
            f"""
            QWidget#mapStatusCard {{
                background: {bg};
                border: 1px solid {soften(accent, 0.45)};
                border-radius: 12px;
            }}
            """
        )
