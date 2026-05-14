"""웨이포인트 맵 카드 — 카툰 SVG + 노드 마커 + 로봇 + 라이브 경로 + 사이드 리스트.

rclpy 직접 import 금지 — Control Server REST/SSE 만 사용."""

from __future__ import annotations

import json
import math
import os
import pathlib
import re
import time
from typing import Any

from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, QSize, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QBrush
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QAction, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

DEFAULT_SVG = (pathlib.Path(__file__).resolve().parents[3]
               / "device/gogoping_ws/src/gogoping/gogoping_navigation"
               / "models/pingdergarten/admin_map.svg")


def _svg_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("PINGDER_ADMIN_MAP_SVG", str(DEFAULT_SVG)))


class MapView(QWidget):
    """SVG 배경 + 마커/로봇/경로 오버레이 + Nav2 Goal 클릭-드래그."""

    MAP_ORIGIN = (-11.0, -9.0)
    MAP_RES = 0.025
    MAP_SIZE = (881, 720)
    DRAG_MIN_PX = 12          # 이보다 짧은 드래그는 클릭 실수로 간주, goal 무시

    # 마우스 업 시 (x, y, yaw) — Nav2 Goal 요청 (일반 좌클릭-드래그)
    goal_pose_requested = pyqtSignal(float, float, float)
    # 마우스 업 시 (x, y, yaw) — AMCL 2D Pose Estimate (Shift+좌클릭-드래그)
    initial_pose_requested = pyqtSignal(float, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(QSize(400, 320))
        self.setFocusPolicy(Qt.StrongFocus)            # Esc 키 받을 수 있게
        self.setCursor(Qt.CrossCursor)                  # 맵 위 커서 십자
        self.setMouseTracking(True)                     # hover 좌표 표시용
        self._svg = QSvgRenderer(str(_svg_path()))
        # graph 모드 전용 SVG — 영역 라벨 (<text>) 제거. waypoint 이름과 겹치는 것 방지.
        try:
            svg_text = pathlib.Path(_svg_path()).read_text(encoding='utf-8')
            svg_no_label = re.sub(r'<text\b[^>]*>.*?</text>', '', svg_text, flags=re.DOTALL)
            self._svg_no_label = QSvgRenderer()
            self._svg_no_label.load(svg_no_label.encode('utf-8'))
        except OSError:
            self._svg_no_label = self._svg  # fallback
        # 표시 모드: 'map' = SVG + 로봇/경로만, 'graph' = + waypoint 마커
        self._display_mode: str = 'graph'
        # zoom/pan — Ctrl + 휠로 줌인/아웃, 마우스 위치 중심
        self._zoom: float = 1.0
        self._pan: QPointF = QPointF(0.0, 0.0)
        self._ZOOM_MIN = 1.0
        self._ZOOM_MAX = 8.0
        # 휠 클릭(middle button) 드래그로 pan
        self._pan_drag_start: QPointF | None = None       # widget px (mouse down 시)
        self._pan_at_drag_start: QPointF | None = None    # 드래그 시작 시점의 self._pan
        self._waypoints: list[dict] = []
        self._filter: set[str] | None = None   # 검색 필터 (None = 전체)
        self._robot: dict | None = None
        self._plan: list[tuple[float, float]] = []
        self._current_name: str | None = None
        # hover 시 화면 좌하단에 (x, y) 표시 — vertex 좌표 측정용
        self._hover_pos: QPointF | None = None          # widget px (마우스 위치)
        # 드래그 상태 — _drag_mode: "goal" (코랄, NavigateToPose) | "initial" (녹색, /initialpose)
        self._drag_start: QPointF | None = None
        self._drag_current: QPointF | None = None
        self._drag_mode: str = "goal"
        # 마우스 업 후 짧은 페이드 아웃 피드백
        self._feedback: dict | None = None              # {"start", "end", "started_at", "mode"}
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setInterval(30)
        self._feedback_timer.timeout.connect(self._tick_feedback)

    def set_waypoints(self, wps: list[dict]) -> None:
        self._waypoints = wps; self.update()

    def set_filter(self, names: set[str] | None) -> None:
        """None = 전체 표시, set = 해당 name 만 표시 (검색 결과)."""
        self._filter = names
        self.update()

    def set_display_mode(self, mode: str) -> None:
        """'map' = waypoint 마커 숨김, 'graph' = 마커 표시."""
        if mode not in ('map', 'graph'):
            return
        self._display_mode = mode
        self.update()

    def set_robot(self, x: float, y: float, yaw: float) -> None:
        self._robot = {"x": x, "y": y, "yaw": yaw}; self.update()

    def set_plan(self, points: list[tuple[float, float]]) -> None:
        self._plan = points; self.update()

    def set_current(self, name: str | None) -> None:
        self._current_name = name; self.update()

    def _map_to_widget(self, mx: float, my: float) -> QPointF:
        W = self.width(); H = self.height()
        rx = (mx - self.MAP_ORIGIN[0]) / self.MAP_RES
        ry = self.MAP_SIZE[1] - (my - self.MAP_ORIGIN[1]) / self.MAP_RES
        # 기준 widget 좌표 (zoom=1, pan=0) 후 zoom/pan 적용
        bx = rx * W / self.MAP_SIZE[0]
        by = ry * H / self.MAP_SIZE[1]
        return QPointF(bx * self._zoom + self._pan.x(),
                       by * self._zoom + self._pan.y())

    def _widget_to_map(self, wx: float, wy: float) -> tuple[float, float]:
        """widget px → map frame (미터, Y-up). _map_to_widget 의 역함수."""
        W = self.width(); H = self.height()
        # zoom/pan 역변환 → 기준 widget 좌표
        bx = (wx - self._pan.x()) / self._zoom
        by = (wy - self._pan.y()) / self._zoom
        rx = bx * self.MAP_SIZE[0] / W
        ry = by * self.MAP_SIZE[1] / H
        mx = rx * self.MAP_RES + self.MAP_ORIGIN[0]
        my = self.MAP_ORIGIN[1] + (self.MAP_SIZE[1] - ry) * self.MAP_RES
        return mx, my

    def wheelEvent(self, e: Any) -> None:
        """Ctrl + 휠 → 마우스 위치 중심 zoom in/out."""
        if not (e.modifiers() & Qt.ControlModifier):
            super().wheelEvent(e)
            return
        delta = e.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_zoom = max(self._ZOOM_MIN, min(self._ZOOM_MAX, self._zoom * factor))
        if new_zoom == self._zoom:
            e.accept(); return
        # 마우스 아래의 기준 좌표가 화면에서 안 움직이도록 pan 조정
        mp = e.pos()
        base_x = (mp.x() - self._pan.x()) / self._zoom
        base_y = (mp.y() - self._pan.y()) / self._zoom
        self._zoom = new_zoom
        self._pan = QPointF(mp.x() - base_x * new_zoom,
                            mp.y() - base_y * new_zoom)
        # zoom 1.0 으로 돌아오면 pan 도 reset (정확히 0 이 되도록)
        if abs(self._zoom - 1.0) < 1e-6:
            self._zoom = 1.0
            self._pan = QPointF(0.0, 0.0)
        self.update()
        e.accept()

    # -------- 좌클릭 = Nav2 Goal / Shift+좌클릭 = 2D Pose Estimate / 휠 클릭 pan --------
    def mousePressEvent(self, e: Any) -> None:
        if e.button() == Qt.MidButton:
            self._pan_drag_start = QPointF(e.pos())
            self._pan_at_drag_start = QPointF(self._pan)
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() != Qt.LeftButton:
            return
        self._drag_start = QPointF(e.pos())
        self._drag_current = QPointF(e.pos())
        self._drag_mode = "initial" if (e.modifiers() & Qt.ShiftModifier) else "goal"
        self.setFocus(Qt.MouseFocusReason)
        self.update()

    def mouseMoveEvent(self, e: Any) -> None:
        self._hover_pos = QPointF(e.pos())
        if self._pan_drag_start is not None and self._pan_at_drag_start is not None:
            dx = e.pos().x() - self._pan_drag_start.x()
            dy = e.pos().y() - self._pan_drag_start.y()
            self._pan = QPointF(self._pan_at_drag_start.x() + dx,
                                self._pan_at_drag_start.y() + dy)
        if self._drag_start is not None:
            self._drag_current = QPointF(e.pos())
        self.update()

    def leaveEvent(self, _e: Any) -> None:
        self._hover_pos = None
        self.update()

    def mouseReleaseEvent(self, e: Any) -> None:
        if e.button() == Qt.MidButton and self._pan_drag_start is not None:
            self._pan_drag_start = None
            self._pan_at_drag_start = None
            self.setCursor(Qt.CrossCursor)
            return
        if e.button() != Qt.LeftButton or self._drag_start is None:
            return
        start = self._drag_start
        end = QPointF(e.pos())
        self._drag_start = None
        self._drag_current = None
        self.update()
        # 너무 짧은 드래그 = 실수 클릭, 무시
        dx_w = end.x() - start.x()
        dy_w = end.y() - start.y()
        if (dx_w * dx_w + dy_w * dy_w) ** 0.5 < self.DRAG_MIN_PX:
            return
        # 시작점 = 목표 위치 (x, y), 드래그 방향 = yaw (raster Y-up → atan2(-dy_w, dx_w))
        mx, my = self._widget_to_map(start.x(), start.y())
        yaw = math.atan2(-dy_w, dx_w)
        if self._drag_mode == "initial":
            self.initial_pose_requested.emit(mx, my, yaw)
        else:
            self.goal_pose_requested.emit(mx, my, yaw)
        # 피드백 — 0.5 초간 화살표 페이드 아웃 (mode 별 색 유지)
        self._feedback = {
            "start": QPointF(start), "end": QPointF(end),
            "started_at": time.monotonic(),
            "mode": self._drag_mode,
        }
        self._feedback_timer.start()

    def keyPressEvent(self, e: Any) -> None:
        if e.key() == Qt.Key_Escape and self._drag_start is not None:
            # 진행중 드래그 취소
            self._drag_start = None
            self._drag_current = None
            self.update()
            return
        super().keyPressEvent(e)

    def paintEvent(self, _evt: Any) -> None:
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing, True)
        active_svg = self._svg_no_label if self._display_mode == 'graph' else self._svg
        if active_svg.isValid():
            W = self.width(); H = self.height()
            target = QRectF(self._pan.x(), self._pan.y(),
                            W * self._zoom, H * self._zoom)
            active_svg.render(qp, target)
        # 라이브 경로
        if len(self._plan) >= 2:
            pen = QPen(QColor("#00A86B"), 3, Qt.DashLine)
            pen.setDashPattern([4, 4])
            qp.setPen(pen); qp.setBrush(Qt.NoBrush)
            path = QPainterPath(self._map_to_widget(*self._plan[0]))
            for px, py in self._plan[1:]:
                path.lineTo(self._map_to_widget(px, py))
            qp.drawPath(path)
        # 웨이포인트 마커 (graph 모드에서만) — zoom 에 따라 마커/폰트 같이 확대
        if self._display_mode == 'graph':
            z = self._zoom
            for w in self._waypoints:
                if self._filter is not None and w["name"] not in self._filter:
                    continue
                p = self._map_to_widget(w["x"], w["y"])
                is_current = (w["name"] == self._current_name)
                r = (5 if is_current else 3.5) * z
                qp.setPen(QPen(QColor("#1A6B8A"), 2 * z))
                qp.setBrush(QBrush(QColor("#00A86B" if is_current else "#5BB9E0")))
                qp.drawEllipse(p, r, r)
                # 라벨: zoom 의 sqrt 비례 — 확대해도 천천히 커짐 (인접 충돌 완화)
                fsize = max(7, int(round(7 * math.sqrt(z))))
                qp.setFont(QFont("", fsize, QFont.Bold))
                fm = qp.fontMetrics()
                tw = fm.horizontalAdvance(w["name"]) + 6
                th = fm.height() + 2
                lbl = QRectF(p.x() - tw / 2, p.y() + r + 2, tw, th)
                qp.setPen(Qt.NoPen)
                qp.setBrush(QBrush(QColor(255, 255, 255, 210)))
                qp.drawRoundedRect(lbl, 3, 3)
                qp.setPen(QColor("#1A1A1A"))
                qp.drawText(lbl, Qt.AlignCenter, w["name"])
        # 로봇 마커
        if self._robot is not None:
            p = self._map_to_widget(self._robot["x"], self._robot["y"])
            qp.setPen(QPen(QColor("#222"), 2))
            qp.setBrush(QBrush(QColor("#E07B5B")))
            qp.drawEllipse(p, 8, 8)
            qp.drawLine(
                p,
                QPointF(p.x() + 15 * math.cos(-self._robot["yaw"]),
                        p.y() + 15 * math.sin(-self._robot["yaw"])),
            )
        # 드래그 미리보기 화살표 (goal=코랄 / initial=녹색) + 마우스 업 후 피드백
        if self._drag_start is not None and self._drag_current is not None:
            self._paint_arrow_at(qp, self._drag_start, self._drag_current, 1.0, self._drag_mode)
        if self._feedback is not None:
            elapsed = time.monotonic() - self._feedback["started_at"]
            if elapsed < 0.5:
                alpha = 1.0 - elapsed / 0.5
                self._paint_arrow_at(qp, self._feedback["start"], self._feedback["end"],
                                     alpha, self._feedback.get("mode", "goal"))
        # hover 좌표 표시 — 좌하단에 (x, y) m
        if self._hover_pos is not None:
            mx, my = self._widget_to_map(self._hover_pos.x(), self._hover_pos.y())
            label = f"x={mx:+.3f}  y={my:+.3f}  m"
            qp.setFont(QFont("monospace", 10, QFont.Bold))
            fm = qp.fontMetrics()
            tw = fm.horizontalAdvance(label) + 12
            th = fm.height() + 6
            box = QRectF(8, self.height() - th - 8, tw, th)
            qp.setPen(Qt.NoPen)
            qp.setBrush(QBrush(QColor(0, 0, 0, 160)))
            qp.drawRoundedRect(box, 4, 4)
            qp.setPen(QColor("#FFFFFF"))
            qp.drawText(box, Qt.AlignCenter, label)

    def _tick_feedback(self) -> None:
        if self._feedback is None:
            self._feedback_timer.stop()
            return
        elapsed = time.monotonic() - self._feedback["started_at"]
        if elapsed >= 0.5:
            self._feedback = None
            self._feedback_timer.stop()
        self.update()

    # 화살표 컬러 팔레트 — mode 별 (drag preview + feedback fade 공통 사용)
    _ARROW_COLORS = {
        "goal":    {  # 코랄 — Nav2 Goal (로봇이 갈 곳)
            "fill": (224, 123, 91), "outline": (166, 82, 56), "head": (210, 102, 72),
        },
        "initial": {  # 녹색 — 2D Pose Estimate (AMCL 위치 재설정)
            "fill": (90, 200, 145), "outline": (32, 124, 87), "head": (52, 168, 117),
        },
    }

    def _paint_arrow_at(self, qp: QPainter, s: QPointF, e: QPointF,
                        alpha: float, mode: str = "goal") -> None:
        """공통 화살표 — drag preview + feedback fade 둘 다 사용.
        mode: "goal" (코랄) | "initial" (녹색).
        alpha ∈ [0, 1] — 모든 색 채널에 곱해서 fade 구현."""
        palette = self._ARROW_COLORS.get(mode, self._ARROW_COLORS["goal"])
        a = max(0, min(255, int(255 * alpha)))
        dx = e.x() - s.x()
        dy = e.y() - s.y()
        dist = (dx * dx + dy * dy) ** 0.5

        # 시작 origin 점 (항상 표시)
        qp.setPen(QPen(QColor(*palette["outline"], a), 2))
        qp.setBrush(QBrush(QColor(*palette["fill"], a)))
        qp.drawEllipse(s, 5, 5)

        if dist < 6:
            return  # 매우 짧은 드래그는 origin 점만

        ux = dx / dist
        uy = dy / dist
        head_len = min(22.0, max(10.0, dist * 0.32))
        head_w = head_len * 0.7
        shaft_end = QPointF(e.x() - ux * head_len * 0.55,
                            e.y() - uy * head_len * 0.55)

        # 그림자
        qp.setPen(QPen(QColor(0, 0, 0, int(35 * alpha)), 6, Qt.SolidLine, Qt.RoundCap))
        qp.drawLine(QPointF(s.x() + 1, s.y() + 1),
                    QPointF(shaft_end.x() + 1, shaft_end.y() + 1))

        # shaft
        qp.setPen(QPen(QColor(*palette["fill"], a), 4, Qt.SolidLine, Qt.RoundCap))
        qp.drawLine(s, shaft_end)

        # 화살표 머리
        perp_x = -uy
        perp_y = ux
        tip = QPointF(e.x(), e.y())
        base_l = QPointF(e.x() - ux * head_len + perp_x * head_w * 0.5,
                         e.y() - uy * head_len + perp_y * head_w * 0.5)
        base_r = QPointF(e.x() - ux * head_len - perp_x * head_w * 0.5,
                         e.y() - uy * head_len - perp_y * head_w * 0.5)
        head_path = QPainterPath(tip)
        head_path.lineTo(base_l)
        head_path.lineTo(base_r)
        head_path.closeSubpath()
        qp.setPen(QPen(QColor(*palette["outline"], a), 1))
        qp.setBrush(QBrush(QColor(*palette["head"], a)))
        qp.drawPath(head_path)


class _SseDispatcher:
    """SSE 이벤트 → 위젯 메서드 호출 dispatch (sync, 테스트 용이)."""

    def __init__(self, card: "WaypointMapCard") -> None:
        self.card = card

    def handle(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "odom":
            self.card.update_robot(ev["x"], ev["y"], ev["yaw"])
        elif t == "plan":
            self.card.update_plan([tuple(p) for p in ev.get("points", [])])
        elif t == "goal_status":
            self.card.update_goal_status(ev.get("name"), ev.get("status"))
        elif t == "waypoints":
            self.card._refresh_list()


class _SseThread(QThread):
    """5초 backoff 로 SSE 재연결. event 수신 시 signal emit."""

    event_received = pyqtSignal(dict)

    def __init__(self, url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._url = url
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        import httpx
        import time
        while not self._stop:
            try:
                with httpx.stream("GET", self._url, timeout=None) as r:
                    for line in r.iter_lines():
                        if self._stop: return
                        if line.startswith("data:"):
                            try:
                                ev = json.loads(line.removeprefix("data:").strip())
                                self.event_received.emit(ev)
                            except json.JSONDecodeError:
                                pass
            except Exception:
                time.sleep(5.0)


class WaypointMapCard(QFrame):
    """카드 컨테이너 — MapView + 사이드 리스트 + 상태 라벨."""

    def __init__(self, control_url: str = "http://localhost:8000",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._control_url = control_url
        self.setObjectName("waypointMapCard")
        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self._title = QLabel("실내 맵 · 웨이포인트")
        self._status = QLabel("")
        self._status.setStyleSheet("color: #00A86B; font-weight: bold;")
        # 모드 토글 — segmented control 스타일 (map / graph map)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._btn_map = QPushButton("map")
        self._btn_graph = QPushButton("graph map")
        for btn in (self._btn_map, self._btn_graph):
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(28)
        self._btn_graph.setChecked(True)
        self._mode_group.addButton(self._btn_map, 0)
        self._mode_group.addButton(self._btn_graph, 1)
        self._btn_map.clicked.connect(lambda: self._set_mode('map'))
        self._btn_graph.clicked.connect(lambda: self._set_mode('graph'))
        # segmented control: 두 버튼이 한 덩어리, 좌/우 모서리만 둥글게
        seg_qss = """
            QPushButton {
                background: #FFFFFF;
                color: #1A6B8A;
                border: 1.5px solid #5BB9E0;
                padding: 0 14px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover { background: #EAF6FB; }
            QPushButton:checked {
                background: #1A6B8A;
                color: #FFFFFF;
                border-color: #1A6B8A;
            }
        """
        self._btn_map.setStyleSheet(seg_qss + """
            QPushButton {
                border-top-left-radius: 8px;
                border-bottom-left-radius: 8px;
                border-right-width: 0.75px;
            }
        """)
        self._btn_graph.setStyleSheet(seg_qss + """
            QPushButton {
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
                border-left-width: 0.75px;
            }
        """)
        header.addWidget(self._title)
        header.addStretch(1)
        header.addWidget(self._status)
        header.addSpacing(12)
        header.addWidget(self._btn_map)
        header.addWidget(self._btn_graph)
        layout.addLayout(header)

        body = QHBoxLayout()
        self._map = MapView()
        self._map.goal_pose_requested.connect(self._on_goal_pose_requested)
        self._map.initial_pose_requested.connect(self._on_initial_pose_requested)
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_context_menu)
        # graph 모드 사이드: 검색창 + 리스트
        self._search = QLineEdit()
        self._search.setPlaceholderText("이름 검색…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)
        self._search.setStyleSheet("""
            QLineEdit {
                background: #FFFFFF;
                color: #1A6B8A;
                border: 1.5px solid #5BB9E0;
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QLineEdit:focus { border-color: #1A6B8A; }
        """)
        list_container = QWidget()
        list_box = QVBoxLayout(list_container)
        list_box.setContentsMargins(0, 0, 0, 0)
        list_box.setSpacing(4)
        list_box.addWidget(self._search)
        list_box.addWidget(self._list)
        # 리스트 자리를 stack 으로 감싸 — map 모드에서도 가로 비율 유지 (빈 placeholder 와 swap)
        self._list_stack = QStackedWidget()
        self._list_stack.setFixedWidth(180)
        self._list_stack.addWidget(list_container)    # index 0: graph mode
        self._list_stack.addWidget(QWidget())         # index 1: map mode (empty)
        body.addWidget(self._map, 1); body.addWidget(self._list_stack)
        layout.addLayout(body)

        # 테스트 접근용
        self._svg_renderer = self._map._svg

        QTimer.singleShot(0, self._refresh_list)

        self._dispatcher = _SseDispatcher(self)
        self._sse = _SseThread(f"{control_url}/waypoints/events", self)
        self._sse.event_received.connect(self._dispatcher.handle)
        self._sse.start()

    def _set_mode(self, mode: str) -> None:
        """map / graph 토글 — MapView 마커 + 사이드 리스트 동시 제어.
        리스트는 visibility 가 아니라 빈 placeholder 와 swap (가로 비율 유지)."""
        self._map.set_display_mode(mode)
        self._list_stack.setCurrentIndex(0 if mode == 'graph' else 1)

    def _on_search_changed(self, text: str) -> None:
        """검색어로 사이드 리스트 + MapView 마커 필터."""
        q = text.strip().lower()
        # 사이드 리스트: 매칭 안 되는 행 숨김
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setHidden(bool(q) and q not in item.text().lower())
        # MapView 도 매칭 항목만 표시 (검색어 비어있으면 전체)
        if not q:
            self._map.set_filter(None)
        else:
            names = {w["name"] for w in self._map._waypoints
                     if q in w["name"].lower()}
            self._map.set_filter(names)

    def update_robot(self, x: float, y: float, yaw: float) -> None:
        self._map.set_robot(x, y, yaw)

    def update_plan(self, points: list[tuple[float, float]]) -> None:
        self._map.set_plan(points)

    def update_goal_status(self, name: str | None, status: str | None) -> None:
        if status in ("active", "pending") and name:
            self._status.setText(f"→ {name}")
            self._map.set_current(name)
            self._highlight(name)
        else:
            self._status.setText("")
            self._map.set_current(None)
            self._highlight(None)

    def _refresh_list(self) -> None:
        import httpx
        try:
            r = httpx.get(f"{self._control_url}/waypoints", timeout=2.0)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError:
            return
        self._map.set_waypoints(data["waypoints"])
        self._list.clear()
        for w in data["waypoints"]:
            it = QListWidgetItem(w["name"])
            it.setData(Qt.UserRole, w["name"])
            self._list.addItem(it)

    def _highlight(self, name: str | None) -> None:
        for i in range(self._list.count()):
            it = self._list.item(i)
            stored = it.data(Qt.UserRole)
            it.setText(("▶ " if stored == name else "") + stored)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        import httpx
        name = item.data(Qt.UserRole)
        try:
            httpx.post(
                f"{self._control_url}/waypoints/goto",
                json={"name": name}, timeout=2.0,
            )
        except httpx.HTTPError:
            pass

    def _on_list_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        name = item.data(Qt.UserRole)
        menu = QMenu(self._list)
        delete_act = QAction(f"🗑  '{name}' 삭제", menu)
        delete_act.triggered.connect(lambda: self._on_delete(name))
        menu.addAction(delete_act)
        menu.exec_(self._list.viewport().mapToGlobal(pos))

    def _on_delete(self, name: str) -> None:
        import httpx
        reply = QMessageBox.question(
            self, "웨이포인트 삭제",
            f"'{name}' 을 삭제할까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            r = httpx.delete(
                f"{self._control_url}/waypoints/{name}", timeout=2.0,
            )
        except httpx.HTTPError as e:
            QMessageBox.critical(self, "통신 오류", str(e))
            return
        if r.status_code == 200:
            # SSE waypoints 이벤트가 도착하면 자동 갱신되지만 안전 위해 직접도 한 번
            self._refresh_list()
            return
        try:
            msg = r.json().get("detail", r.text)
        except Exception:
            msg = r.text
        QMessageBox.warning(self, "삭제 실패", msg)

    def _on_goal_pose_requested(self, x: float, y: float, yaw: float) -> None:
        """MapView 의 클릭-드래그 → /waypoints/goto-pose 호출 (RViz Nav2 Goal)."""
        import httpx
        try:
            httpx.post(
                f"{self._control_url}/waypoints/goto-pose",
                json={"x": x, "y": y, "yaw": yaw}, timeout=2.0,
            )
        except httpx.HTTPError:
            pass  # 사용자 액션 — 실패해도 silent (SSE goal_status 가 결과 알림)

    def _on_initial_pose_requested(self, x: float, y: float, yaw: float) -> None:
        """MapView 의 Shift+클릭-드래그 → /waypoints/initialpose 호출 (RViz 2D Pose Estimate).
        AMCL 의 위치 추정을 (x, y, yaw) 근처로 재초기화 — 로봇은 움직이지 않음."""
        import httpx
        try:
            httpx.post(
                f"{self._control_url}/waypoints/initialpose",
                json={"x": x, "y": y, "yaw": yaw}, timeout=2.0,
            )
        except httpx.HTTPError:
            pass

    def closeEvent(self, e: Any) -> None:
        self._sse.stop()
        self._sse.wait(2000)
        super().closeEvent(e)
