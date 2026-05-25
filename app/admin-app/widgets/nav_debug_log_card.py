"""NavDebugLogCard — ``/ws/nav-debug-events`` 실시간 로그 표시.

cancel chain 디버깅용. 한 줄당 ``[HH:MM:SS.fff] [SOURCE] msg`` 형식, source/level
별 색상. 마지막 N=200 줄 유지.

GogoPing DebugDrawer 의 네 번째 슬롯에 들어감 (DebugStatePanel / BatteryDebugSlider /
PoseDebugPanel 옆).

WS 콜백이 daemon thread 에서 호출되므로 Qt signal 로 main thread 로 marshal.

기능:
- ⛶ Pop-out: 별창 (QDialog) 으로 풀스크린 디스플레이 — 듀얼 모니터 활용
- 필터: source / level 체크박스 — 노이즈 끄고 켜기
- ⏸ Pause: 일시정지 + paused 카운터
- 💾 Export: 원본 payload (.jsonl) 저장 — 사후 분석용
"""
from __future__ import annotations

import json
import time
from collections import deque
from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QTextCursor
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


# source 별 색상 — 어두운 배경에 잘 보이는 톤
_COLORS = {
    "SetGoal":   "#4fc3f7",   # cyan — 외부 명령 수신
    "reconcile": "#80deea",   # 옅은 cyan — reconciler 결과
    "FSM":       "#ffd54f",   # yellow — state 변경
    "BT swap":   "#ffb74d",   # orange — 트리 교체
    "SubBT":     "#4db6ac",   # teal — SubTree Sequence 안 active leaf 변경
    "NavTo":     "#81c784",   # green — BT behavior 자체
    "graph_rt":  "#7986cb",   # indigo — graph_router (cancel forward 등). 빨강은 err 전용.
    "CamPan":    "#8d6e63",   # brown — servo pan 명령 (PanCameraSweep / admin 슬라이더 / teleop)
    "UI":        "#ba68c8",   # lavender — UIPublisher 이벤트 (lullaby/announce/countdown)
    "AdminUI":   "#f06292",   # magenta — admin UI 가 누른 버튼 / 입력
    "TEST":      "#9e9e9e",   # gray
}
_DEFAULT_COLOR = "#bdbdbd"

# 알려진 모든 source 목록 (체크박스 순서) — _COLORS 키와 동일.
_ALL_SOURCES = list(_COLORS.keys())
_ALL_LEVELS = ("info", "warn", "err")

# level 별 강조 — warn/err 는 항상 빨강·주황으로 override
_LEVEL_OVERRIDE = {
    "warn": "#ffb300",   # amber
    "err":  "#ef5350",   # red
}

_MAX_LINES = 200


class _LogView(QWidget):
    """순수 로그 표시 컴포넌트 (QGroupBox 래핑 없음).

    Card 와 Popout 이 같은 코드로 동작 — 둘 다 자기 _buffer, _filters, _paused 보유.
    부모 (NavDebugLogCard) 가 ``append_event(payload)`` 호출하면 둘 다에 forward.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        with_popout_button: bool = True,
        popout_callback=None,
    ) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # ─── 1행: 헤더 버튼 (Pause / Pop-out / Export) ──────────────────────
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)
        self._pause_btn = QPushButton("⏸")
        self._pause_btn.setCheckable(True)
        self._pause_btn.setFixedWidth(32)
        self._pause_btn.setToolTip("일시정지 (paused 동안 새 이벤트는 버퍼만 갱신, 화면 정지)")
        self._pause_btn.clicked.connect(self._on_pause_toggled)
        header.addWidget(self._pause_btn)

        self._pause_count_lbl = QLabel("")
        self._pause_count_lbl.setStyleSheet("color: #888; font-size: 9pt;")
        header.addWidget(self._pause_count_lbl)
        header.addStretch(1)

        if with_popout_button:
            popout_btn = QPushButton("⛶")
            popout_btn.setFixedWidth(28)
            popout_btn.setToolTip("별창으로 풀스크린 표시")
            if popout_callback is not None:
                popout_btn.clicked.connect(popout_callback)
            header.addWidget(popout_btn)

        export_btn = QPushButton("💾")
        export_btn.setFixedWidth(28)
        export_btn.setToolTip("현재 버퍼를 .jsonl 로 저장 (원본 payload)")
        export_btn.clicked.connect(self._on_export_clicked)
        header.addWidget(export_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(56)
        clear_btn.clicked.connect(self._on_clear)
        header.addWidget(clear_btn)
        outer.addLayout(header)

        # ─── 2행: source 필터 (3컬럼 grid) ─────────────────────────────────
        src_lbl = QLabel("Src:")
        src_lbl.setStyleSheet("color: #aaa; font-size: 9pt;")
        outer.addWidget(src_lbl)
        src_grid = QGridLayout()
        src_grid.setContentsMargins(8, 0, 0, 0)
        src_grid.setHorizontalSpacing(8)
        src_grid.setVerticalSpacing(2)
        self._source_checks: dict[str, QCheckBox] = {}
        for i, src in enumerate(_ALL_SOURCES):
            cb = QCheckBox(src)
            cb.setChecked(True)
            cb.setStyleSheet(
                f"QCheckBox {{ color: {_COLORS.get(src, _DEFAULT_COLOR)};"
                f" font-size: 9pt; spacing: 4px; }}"
            )
            cb.toggled.connect(self._rerender)
            self._source_checks[src] = cb
            src_grid.addWidget(cb, i // 3, i % 3)
        outer.addLayout(src_grid)

        # ─── 3행: level 필터 ────────────────────────────────────────────────
        lvl_row = QHBoxLayout()
        lvl_row.setContentsMargins(8, 2, 0, 4)
        lvl_lbl = QLabel("Lvl:")
        lvl_lbl.setStyleSheet("color: #aaa; font-size: 9pt;")
        lvl_row.addWidget(lvl_lbl)
        self._level_checks: dict[str, QCheckBox] = {}
        for lvl in _ALL_LEVELS:
            cb = QCheckBox(lvl)
            cb.setChecked(True)
            color = _LEVEL_OVERRIDE.get(lvl, "#d0d0d4")
            cb.setStyleSheet(
                f"QCheckBox {{ color: {color}; font-size: 9pt; spacing: 4px; }}"
            )
            cb.toggled.connect(self._rerender)
            self._level_checks[lvl] = cb
            lvl_row.addWidget(cb)
        lvl_row.addStretch(1)
        outer.addLayout(lvl_row)

        # ─── 4행: 텍스트 영역 ───────────────────────────────────────────────
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(
            QFont("Cascadia Code, JetBrains Mono, Source Code Pro, monospace", 9)
        )
        self._text.setStyleSheet(
            "QTextEdit { background-color: #1a1a1f; color: #d0d0d4;"
            " border: 1px solid #333; border-radius: 4px; padding: 4px; }"
        )
        self._text.setLineWrapMode(QTextEdit.WidgetWidth)
        self._text.setMinimumHeight(180)
        outer.addWidget(self._text, stretch=1)

        # ─── 5행: footer (auto-scroll + line count) ──────────────────────
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        self._autoscroll = QCheckBox("auto-scroll")
        self._autoscroll.setChecked(True)
        self._autoscroll.setStyleSheet("font-size: 9pt;")
        footer.addWidget(self._autoscroll)
        footer.addStretch(1)
        self._count_lbl = QLabel("0 lines")
        self._count_lbl.setStyleSheet("color: #888; font-size: 9pt;")
        footer.addWidget(self._count_lbl)
        outer.addLayout(footer)

        # ─── 상태 ──────────────────────────────────────────────────────────
        # 원본 payload 보관 — Export 용 + 필터 변경 시 rerender. 표시 줄수와 동일 maxlen.
        self._buffer: deque[dict] = deque(maxlen=_MAX_LINES)
        self._paused = False
        self._pending_during_pause = 0

    # ──────── 외부 진입점 ──────────

    def append_event(self, payload: dict) -> None:
        """daemon thread 에서 호출돼도 OK — Qt signal 로 marshal 한 NavDebugLogCard 가
        main thread 에서 본 메서드를 부른다. 본 클래스는 main thread 만 가정.
        """
        self._buffer.append(payload)
        if self._paused:
            self._pending_during_pause += 1
            self._pause_count_lbl.setText(f"paused, {self._pending_during_pause} new")
            return
        # 필터 통과 시만 화면 append
        if self._passes_filter(payload):
            self._append_line(payload)
        self._count_lbl.setText(f"{len(self._buffer)} lines")

    # ──────── 내부 ─────────────

    def _passes_filter(self, payload: dict) -> bool:
        src = str(payload.get("source", "?"))
        lvl = str(payload.get("level", "info"))
        src_cb = self._source_checks.get(src)
        if src_cb is not None and not src_cb.isChecked():
            return False
        if src_cb is None:
            # 모르는 source — TEST 체크박스 따라가게 (보수적 표시)
            test_cb = self._source_checks.get("TEST")
            if test_cb is not None and not test_cb.isChecked():
                return False
        lvl_cb = self._level_checks.get(lvl)
        if lvl_cb is not None and not lvl_cb.isChecked():
            return False
        return True

    def _format_line(self, payload: dict) -> str:
        ts = float(payload.get("ts", time.time()))
        source = str(payload.get("source", "?"))
        level = str(payload.get("level", "info"))
        msg = str(payload.get("msg", ""))
        color = _LEVEL_OVERRIDE.get(level) or _COLORS.get(source, _DEFAULT_COLOR)
        ts_str = time.strftime("%H:%M:%S", time.localtime(ts))
        frac = int((ts - int(ts)) * 1000)
        ts_str = f"{ts_str}.{frac:03d}"
        msg_html = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return (
            f'<span style="color:#666">[{ts_str}]</span> '
            f'<span style="color:{color}; font-weight:600">[{source:8}]</span> '
            f'<span style="color:{color}">{msg_html}</span>'
        )

    def _append_line(self, payload: dict) -> None:
        # 최대 줄수 — 초과 시 오래된 것부터 삭제 (QTextEdit 의 줄수와 buffer 동기)
        doc = self._text.document()
        if doc.blockCount() >= _MAX_LINES:
            cursor = self._text.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()
        self._text.append(self._format_line(payload))
        if self._autoscroll.isChecked():
            sb = self._text.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _rerender(self) -> None:
        """필터 변경 시 — 텍스트 전체 다시 그림. _buffer 가 source of truth."""
        self._text.clear()
        for payload in self._buffer:
            if self._passes_filter(payload):
                self._text.append(self._format_line(payload))
        self._count_lbl.setText(f"{len(self._buffer)} lines")
        if self._autoscroll.isChecked():
            sb = self._text.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_pause_toggled(self, checked: bool) -> None:
        self._paused = checked
        if checked:
            self._pause_btn.setText("▶")
            self._pending_during_pause = 0
            self._pause_count_lbl.setText("paused")
        else:
            self._pause_btn.setText("⏸")
            self._pause_count_lbl.setText("")
            # resume 시 — 그동안 누락된 화면 갱신
            self._rerender()

    def _on_clear(self) -> None:
        self._text.clear()
        self._buffer.clear()
        self._pending_during_pause = 0
        self._pause_count_lbl.setText("paused" if self._paused else "")
        self._count_lbl.setText("0 lines")

    def _on_export_clicked(self) -> None:
        if not self._buffer:
            return
        default_name = f"nav-debug-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Nav Debug Log", default_name, "JSON Lines (*.jsonl)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for payload in self._buffer:
                    f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            # 사용자에게 직접 알릴 만한 채널이 없으니 마지막 라인에 inline 표시
            err = {
                "ts": time.time(), "source": "TEST", "level": "err",
                "msg": f"export 실패: {e}",
            }
            self._buffer.append(err)
            if self._passes_filter(err):
                self._append_line(err)


class NavDebugLogCard(QGroupBox):
    """SetGoal → reconcile → FSM → BT swap → NavTo → graph_router cancel chain 추적.

    내부 _LogView 가 모든 표시 로직. 본 클래스는 GroupBox 타이틀 + Pop-out QDialog
    관리만 담당.
    """

    # daemon thread → main thread marshal
    _new_event = pyqtSignal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Nav Debug Log", parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 14, 8, 8)
        outer.setSpacing(4)

        self._view = _LogView(
            self, with_popout_button=True, popout_callback=self._toggle_popout,
        )
        outer.addWidget(self._view, stretch=1)

        # popout dialog — 열려있을 때 같은 payload 가 tee 됨
        self._popout: QDialog | None = None
        self._popout_view: _LogView | None = None

        self._new_event.connect(self._dispatch_in_main)

    # 외부 (WS callback) 가 호출 — thread-safe (signal emit)
    def append_event(self, payload: dict) -> None:
        self._new_event.emit(payload)

    def _dispatch_in_main(self, payload: dict) -> None:
        # 인라인 카드 + (활성화돼있다면) popout 둘 다에 forward
        self._view.append_event(payload)
        if self._popout_view is not None:
            self._popout_view.append_event(payload)

    def _toggle_popout(self) -> None:
        if self._popout is not None:
            self._popout.raise_()
            self._popout.activateWindow()
            return
        self._popout = QDialog(self.window())
        self._popout.setWindowTitle("Nav Debug Log — Pop-out")
        self._popout.setMinimumSize(900, 600)
        lay = QVBoxLayout(self._popout)
        lay.setContentsMargins(8, 8, 8, 8)
        self._popout_view = _LogView(
            self._popout, with_popout_button=False, popout_callback=None,
        )
        lay.addWidget(self._popout_view, stretch=1)
        self._popout.finished.connect(self._on_popout_closed)
        # backfill — 인라인 카드 의 현재 buffer 를 popout 에도 보여주기
        for payload in list(self._view._buffer):
            self._popout_view.append_event(payload)
        self._popout.show()

    def _on_popout_closed(self, _result: int) -> None:
        self._popout = None
        self._popout_view = None


__all__ = ["NavDebugLogCard"]
