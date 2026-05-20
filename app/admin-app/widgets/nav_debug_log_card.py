"""NavDebugLogCard — ``/ws/nav-debug-events`` 실시간 로그 표시.

cancel chain 디버깅용. 한 줄당 ``[HH:MM:SS.fff] [SOURCE] msg`` 형식, source/level
별 색상. 마지막 N=200 줄 유지.

GogoPing DebugDrawer 의 네 번째 슬롯에 들어감 (DebugStatePanel / BatteryDebugSlider /
PoseDebugPanel 옆).

WS 콜백이 daemon thread 에서 호출되므로 Qt signal 로 main thread 로 marshal.
"""
from __future__ import annotations

import time
from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


# source 별 색상 — 어두운 배경에 잘 보이는 톤
_COLORS = {
    "SetGoal":   "#4fc3f7",   # cyan — 외부 명령 수신
    "reconcile": "#80deea",   # 옅은 cyan — reconciler 결과
    "FSM":       "#ffd54f",   # yellow — state 변경
    "BT swap":   "#ffb74d",   # orange — 트리 교체
    "NavTo":     "#81c784",   # green — BT behavior 자체
    "graph_rt":  "#e57373",   # red-ish — graph_router (cancel forward 등)
    "TEST":      "#9e9e9e",   # gray
}
_DEFAULT_COLOR = "#bdbdbd"

# level 별 강조 — warn/err 는 항상 빨강·주황으로 override
_LEVEL_OVERRIDE = {
    "warn": "#ffb300",   # amber
    "err":  "#ef5350",   # red
}

_MAX_LINES = 200


class NavDebugLogCard(QGroupBox):
    """SetGoal → reconcile → FSM → BT swap → NavTo → graph_router cancel chain 추적."""

    # daemon thread → main thread marshal
    _new_event = pyqtSignal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__("Nav Debug Log", parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 14, 8, 8)
        outer.setSpacing(6)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Cascadia Code, JetBrains Mono, Source Code Pro, monospace", 9))
        self._text.setStyleSheet(
            "QTextEdit { background-color: #1a1a1f; color: #d0d0d4;"
            " border: 1px solid #333; border-radius: 4px; padding: 4px; }"
        )
        self._text.setLineWrapMode(QTextEdit.WidgetWidth)
        self._text.setMinimumHeight(180)
        outer.addWidget(self._text)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self._autoscroll = QCheckBox("auto-scroll")
        self._autoscroll.setChecked(True)
        row.addWidget(self._autoscroll)
        row.addStretch(1)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._text.clear)
        row.addWidget(clear_btn)
        outer.addLayout(row)

        self._line_count = 0
        self._new_event.connect(self._append_in_main)

    # 외부 (WS callback) 가 호출 — thread-safe (signal emit)
    def append_event(self, payload: dict) -> None:
        self._new_event.emit(payload)

    def _append_in_main(self, payload: dict) -> None:
        ts = float(payload.get("ts", time.time()))
        source = str(payload.get("source", "?"))
        level = str(payload.get("level", "info"))
        msg = str(payload.get("msg", ""))

        color = _LEVEL_OVERRIDE.get(level) or _COLORS.get(source, _DEFAULT_COLOR)

        ts_str = time.strftime("%H:%M:%S", time.localtime(ts))
        frac = int((ts - int(ts)) * 1000)
        ts_str = f"{ts_str}.{frac:03d}"

        # HTML one-liner — color 만 inline, escape 필수
        msg_html = (msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        line = (
            f'<span style="color:#666">[{ts_str}]</span> '
            f'<span style="color:{color}; font-weight:600">[{source:8}]</span> '
            f'<span style="color:{color}">{msg_html}</span>'
        )

        # 최대 줄수 — 초과 시 오래된 것부터 삭제
        if self._line_count >= _MAX_LINES:
            cursor = self._text.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()  # 줄바꿈
        else:
            self._line_count += 1

        self._text.append(line)
        if self._autoscroll.isChecked():
            sb = self._text.verticalScrollBar()
            sb.setValue(sb.maximum())


__all__ = ["NavDebugLogCard"]
