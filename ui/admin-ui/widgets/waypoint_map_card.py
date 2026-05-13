"""웨이포인트 맵 카드 — 카툰 SVG + 노드 마커 + 로봇 + 라이브 경로 + 사이드 리스트.

rclpy 직접 import 금지 — Control Server REST/SSE 만 사용."""

from __future__ import annotations

import json
import math
import os
import pathlib
from typing import Any

from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, QSize, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QBrush
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QAction, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QVBoxLayout, QWidget,
)

DEFAULT_SVG = (pathlib.Path(__file__).resolve().parents[3]
               / "device/gogoping_ws/src/gogoping/gogoping_navigation"
               / "models/pingdergarten/admin_map.svg")


def _svg_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("PINGDER_ADMIN_MAP_SVG", str(DEFAULT_SVG)))


class MapView(QWidget):
    """SVG 배경 + 마커/로봇/경로 오버레이."""

    MAP_ORIGIN = (-11.0, -9.0)
    MAP_RES = 0.025
    MAP_SIZE = (881, 720)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(QSize(400, 320))
        self._svg = QSvgRenderer(str(_svg_path()))
        self._waypoints: list[dict] = []
        self._robot: dict | None = None
        self._plan: list[tuple[float, float]] = []
        self._current_name: str | None = None

    def set_waypoints(self, wps: list[dict]) -> None:
        self._waypoints = wps; self.update()

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
        return QPointF(rx * W / self.MAP_SIZE[0], ry * H / self.MAP_SIZE[1])

    def paintEvent(self, _evt: Any) -> None:
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing, True)
        if self._svg.isValid():
            self._svg.render(qp, QRectF(0, 0, self.width(), self.height()))
        # 라이브 경로
        if len(self._plan) >= 2:
            pen = QPen(QColor("#00A86B"), 3, Qt.DashLine)
            pen.setDashPattern([4, 4])
            qp.setPen(pen); qp.setBrush(Qt.NoBrush)
            path = QPainterPath(self._map_to_widget(*self._plan[0]))
            for px, py in self._plan[1:]:
                path.lineTo(self._map_to_widget(px, py))
            qp.drawPath(path)
        # 웨이포인트 마커
        for w in self._waypoints:
            p = self._map_to_widget(w["x"], w["y"])
            is_current = (w["name"] == self._current_name)
            r = 10 if is_current else 7
            qp.setPen(QPen(QColor("#1A6B8A"), 2))
            qp.setBrush(QBrush(QColor("#00A86B" if is_current else "#5BB9E0")))
            qp.drawEllipse(p, r, r)
            qp.setPen(QColor("#333"))
            qp.setFont(QFont("", 9, QFont.Bold))
            qp.drawText(QRectF(p.x() - 60, p.y() + 10, 120, 18),
                        Qt.AlignCenter, w["name"])
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
        header.addWidget(self._title); header.addStretch(1); header.addWidget(self._status)
        layout.addLayout(header)

        body = QHBoxLayout()
        self._map = MapView()
        self._list = QListWidget()
        self._list.setFixedWidth(180)
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_context_menu)
        body.addWidget(self._map, 1); body.addWidget(self._list)
        layout.addLayout(body)

        # 테스트 접근용
        self._svg_renderer = self._map._svg

        QTimer.singleShot(0, self._refresh_list)

        self._dispatcher = _SseDispatcher(self)
        self._sse = _SseThread(f"{control_url}/waypoints/events", self)
        self._sse.event_received.connect(self._dispatcher.handle)
        self._sse.start()

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

    def closeEvent(self, e: Any) -> None:
        self._sse.stop()
        self._sse.wait(2000)
        super().closeEvent(e)
