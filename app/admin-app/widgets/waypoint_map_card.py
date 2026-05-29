"""웨이포인트 맵 카드 — SLAM PGM 배경 + 노드 마커 + 로봇 + 라이브 경로 + 사이드 리스트.

rclpy 직접 import 금지 — Control Server REST/SSE 만 사용."""

from __future__ import annotations

import json
import math
import os
import pathlib
import time
from typing import Any

from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF, QSize, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QBrush, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import (
    QAction, QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

DEFAULT_MAP_PGM = (pathlib.Path(__file__).resolve().parents[3]
                   / "controller/gogoping-controller/src/gogoping/gogoping_navigation"
                   / "maps/admin_map_color.png")
DEFAULT_MAP_SVG = DEFAULT_MAP_PGM.with_name("admin_overlay.svg")


def _map_pgm_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("PINGDER_ADMIN_MAP_PGM", str(DEFAULT_MAP_PGM)))


def _map_svg_path() -> pathlib.Path:
    return pathlib.Path(os.environ.get("PINGDER_ADMIN_MAP_SVG", str(DEFAULT_MAP_SVG)))


class MapView(QWidget):
    """SLAM PGM 배경 + 마커/로봇/경로 오버레이 + Nav2 Goal 클릭-드래그."""

    MAP_ORIGIN = (-10.004, -6.958)
    MAP_RES = 0.050
    MAP_SIZE = (580, 440)
    DRAG_MIN_PX = 12          # 이보다 짧은 드래그는 클릭 실수로 간주, goal 무시
    NODE_HIT_PX = 16          # 편집 모드 노드 hit 반경 (widget px)
    LANE_HIT_PX = 8           # 편집 모드 lane hit perpendicular 거리 (widget px)

    # 마우스 업 시 (x, y, yaw) — Nav2 Goal 요청 (일반 좌클릭-드래그)
    goal_pose_requested = pyqtSignal(float, float, float)
    # 마우스 업 시 (x, y, yaw) — AMCL 2D Pose Estimate (Shift+좌클릭-드래그)
    initial_pose_requested = pyqtSignal(float, float, float)
    # 편집 모드 — 노드 두 번 클릭으로 lane 생성 (from, to)
    lane_create_requested = pyqtSignal(str, str)
    # 편집 모드 — Delete 키로 lane 끊기 (from, to)
    lane_delete_requested = pyqtSignal(str, str)
    # 편집 모드 — 노드 드래그 release 후 yaw 확정 (name, x, y, yaw)
    node_move_requested = pyqtSignal(str, float, float, float)
    # 편집 모드 — 빈 곳 드래그 release → 이름 입력 팝업 트리거 (start_widget, end_widget)
    add_drag_release_requested = pyqtSignal(QPointF, QPointF)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(QSize(400, 320))
        self.setFocusPolicy(Qt.StrongFocus)            # Esc 키 받을 수 있게
        self.setCursor(Qt.CrossCursor)                  # 맵 위 커서 십자
        self.setMouseTracking(True)                     # hover 좌표 표시용
        self._map_pixmap = QPixmap(str(_map_pgm_path()))
        svg_path = _map_svg_path()
        self._map_svg = QSvgRenderer(str(svg_path)) if svg_path.exists() else None
        # 표시 모드: 'map' = 배경 + 로봇/경로만, 'graph' = + waypoint 마커
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
        self._lanes: list[dict] = []           # [{from, to, bidirectional}, ...]
        self._route: list[str] | None = None   # vertex name sequence — 강조선
        # patrol 시각화 — vertex 동그라미 안에 번호 / 도착 완료 vertex 는 X.
        # 빈 리스트 / current_index == -1 면 미진행 (overlay 안 그림).
        self._patrol_vertices: list[str] = []
        self._patrol_current_index: int = -1
        self._robot: dict | None = None
        self._plan: list[tuple[float, float]] = []
        self._current_name: str | None = None
        # hover 시 화면 좌하단에 (x, y) 표시 — vertex 좌표 측정용
        self._hover_pos: QPointF | None = None          # widget px (마우스 위치)
        # 드래그 상태 — _drag_mode: "goal" (코랄, NavigateToPose) | "initial" (녹색, /initialpose)
        self._drag_start: QPointF | None = None
        self._drag_current: QPointF | None = None
        self._drag_mode: str = "goal"
        # 편집 모드 상태머신 — Task 19+ (편집 모드 ON 일 때만 활성)
        # state: "ready" → ("node_pressed"|"empty_pressed"|"node_drag"|"add_drag"
        #                  | "yaw_preview" | "link_pending" | "lane_selected")
        self._edit_mode: bool = False
        self._edit_state: str = "ready"
        self._pressed_node: str | None = None      # mousePress 시점 잡힌 노드
        self._selected_node: str | None = None      # LINK_PENDING 의 1차 노드
        self._selected_lane: tuple[str, str] | None = None
        self._yaw_preview: dict | None = None       # {name, new_x, new_y, end_widget}
        self._hover_target: dict | None = None      # {kind: "node"|"lane", id}
        # [이동] 메뉴로 진입한 이동 대상 노드 — node_move_picking / _drag 상태에서 사용
        self._move_target_node: str | None = None
        # 마우스 업 후 짧은 페이드 아웃 피드백
        self._feedback: dict | None = None              # {"start", "end", "started_at", "mode"}
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setInterval(30)
        self._feedback_timer.timeout.connect(self._tick_feedback)

    def set_waypoints(self, wps: list[dict]) -> None:
        self._waypoints = wps; self.update()

    def set_lanes(self, lanes: list[dict]) -> None:
        self._lanes = lanes; self.update()

    def set_route(self, vertex_names: list[str] | None) -> None:
        """다익스트라 결과 강조선. None = 강조 해제."""
        self._route = vertex_names; self.update()

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

    def set_patrol(self, vertices: list[str] | None, current_index: int = -1) -> None:
        """patrol 진행 시각화. vertices: 정렬된 vertex 이름 리스트. current_index: -1=미진행, N=완료.

        vertex 별 표시:
          - 인덱스 < current_index : ✕ (방문 완료)
          - 인덱스 == current_index : 강조색 동그라미 + 번호 (현재 진행)
          - 인덱스 > current_index : 번호만 (대기)
        """
        self._patrol_vertices = list(vertices or [])
        self._patrol_current_index = int(current_index)
        self.update()

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
        # 편집 모드 우클릭 = 더블클릭과 동일 (노드/간선 context menu)
        if e.button() == Qt.RightButton and self._edit_mode:
            target = self._hit_test(QPointF(e.pos()))
            if target is None:
                return
            if target["kind"] == "node":
                self.node_double_clicked.emit(target["id"])
            elif target["kind"] == "lane":
                from_, to = target["id"]
                self.lane_double_clicked.emit(from_, to)
            return
        if e.button() != Qt.LeftButton:
            return

        # ───── 편집 모드 분기 ─────
        if self._edit_mode:
            # NODE_MOVE_PICKING — [이동] 메뉴 선택 후 맵 클릭+드래그 대기
            # 좌클릭: 클릭 시점 = 새 위치, 드래그 방향 = yaw. release 에서 emit.
            if self._edit_state == "node_move_picking":
                self._drag_start = QPointF(e.pos())
                self._drag_current = QPointF(e.pos())
                self._drag_mode = "goal"
                self._edit_state = "node_move_drag"
                self.setFocus(Qt.MouseFocusReason)
                self.update()
                return
            # yaw_preview 상태에서의 클릭 = yaw 확정 (NODE_DRAG 다음 단계)
            if self._edit_state == "yaw_preview":
                self._commit_yaw_preview(QPointF(e.pos()))
                return
            target = self._hit_test(QPointF(e.pos()))
            # ADD_LANE 모드 — 노드 두 번 클릭으로 lane 생성
            if self._edit_state in ("add_lane_mode", "link_pending"):
                if target and target["kind"] == "node":
                    self._handle_node_short_click(target["id"])
                else:
                    # 빈 곳/간선 클릭 → ADD_LANE 모드는 그대로 유지 (다음 노드 대기)
                    pass
                self.update()
                return
            # ADD_NODE 모드 — 빈 곳 드래그 시작
            if self._edit_state == "add_node_mode":
                # 노드 위 클릭은 무시 (빈 곳에서만 드래그 가능)
                if target is None:
                    self._pressed_node = None
                    self._drag_start = QPointF(e.pos())
                    self._drag_current = QPointF(e.pos())
                    self._edit_state = "add_drag"
                self.setFocus(Qt.MouseFocusReason)
                self.update()
                return
            # 기본 편집 동작 — 간선 선택만 (노드 드래그 이동은 더블/우클릭 메뉴로만)
            if target and target["kind"] == "node":
                # 노드 좌클릭은 selection 만 — 이동은 더블/우클릭 메뉴 [이동] 으로
                self._pressed_node = None
            elif target and target["kind"] == "lane":
                self._selected_lane = target["id"]
                self._selected_node = None
                self._edit_state = "lane_selected"
            else:
                # 빈 곳 — selection 해제
                self._pressed_node = None
                self._selected_lane = None
                if self._edit_state == "lane_selected":
                    self._edit_state = "ready"
            self.setFocus(Qt.MouseFocusReason)
            self.update()
            return
        # ─────────────────────────

        # 평소 모드:
        #   - map 모드: 빈 좌클릭-드래그 → Nav2 Goal (기존 동작, 복구)
        #   - graph 모드: 빈 좌클릭-드래그 → 무동작 (편집 모드만 의미 있음)
        #   - Shift+드래그 → AMCL initialpose (양쪽 모드 동일)
        is_shift = bool(e.modifiers() & Qt.ShiftModifier)
        if not is_shift and self._display_mode != 'map':
            # graph 모드 평소 좌클릭 — 무동작
            return
        self._drag_start = QPointF(e.pos())
        self._drag_current = QPointF(e.pos())
        self._drag_mode = "initial" if is_shift else "goal"
        self.setFocus(Qt.MouseFocusReason)
        self.update()

    def mouseMoveEvent(self, e: Any) -> None:
        self._hover_pos = QPointF(e.pos())
        # 편집 모드 hover — 노드/간선 위 시각 강조
        if self._edit_mode:
            new_hover = self._hit_test(QPointF(e.pos()))
            if new_hover != self._hover_target:
                self._hover_target = new_hover
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
        dx_w = end.x() - start.x()
        dy_w = end.y() - start.y()
        drag_dist = (dx_w * dx_w + dy_w * dy_w) ** 0.5

        # ───── 편집 모드 release 분기 ─────
        if self._edit_mode:
            if self._edit_state == "node_move_drag":
                # [이동] 메뉴 → 클릭+드래그 release → 노드 이동 emit.
                # 짧은 클릭이면 yaw = 기존값 유지 (좌표만 이동).
                name = self._move_target_node
                if name is not None:
                    mx, my = self._widget_to_map(start.x(), start.y())
                    if drag_dist >= self.DRAG_MIN_PX:
                        yaw = math.atan2(-dy_w, dx_w)
                    else:
                        wp = next((w for w in self._waypoints
                                   if w["name"] == name), None)
                        yaw = float(wp.get("yaw", 0.0)) if wp else 0.0
                    self.node_move_requested.emit(name, mx, my, yaw)
                self._move_target_node = None
                self._selected_node = None
                self._edit_state = "ready"
                self.update()
                return
            if self._edit_state == "node_pressed":
                if drag_dist < self.DRAG_MIN_PX:
                    # 짧은 클릭 — 기본 모드 (add 모드 아님) 에서는 무동작
                    # (간선 잇기는 [+ 간선 연결] 모드 진입 후에만 동작)
                    self._edit_state = "ready"
                    self._pressed_node = None
                else:
                    # 드래그 → YAW_PREVIEW 진입 (NODE_DRAG)
                    self._enter_yaw_preview(end)
            elif self._edit_state == "add_drag":
                if drag_dist >= self.DRAG_MIN_PX:
                    # add_drag → 이름 팝업 트리거
                    self.add_drag_release_requested.emit(start, end)
                # 짧은 클릭은 무동작 — 모드는 유지
                # 팝업 결과에 따라 ready 로 돌아갈지 결정 (card 측에서)
                self._edit_state = "add_node_mode"
            self.update()
            return
        # ─────────────────────────────────

        self.update()
        # 평소 모드 — 너무 짧은 드래그 = 실수 클릭, 무시
        if drag_dist < self.DRAG_MIN_PX:
            return
        # 시작점 = 목표 위치 (x, y), 드래그 방향 = yaw
        mx, my = self._widget_to_map(start.x(), start.y())
        yaw = math.atan2(-dy_w, dx_w)
        if self._drag_mode == "initial":
            self.initial_pose_requested.emit(mx, my, yaw)
        else:
            # map 모드 평소 좌클릭-드래그 → Nav2 Goal (graph 모드면 press 단계에서 차단됨)
            self.goal_pose_requested.emit(mx, my, yaw)
        # 피드백 — 0.5 초간 화살표 페이드 아웃 (mode 별 색 유지)
        self._feedback = {
            "start": QPointF(start), "end": QPointF(end),
            "started_at": time.monotonic(),
            "mode": self._drag_mode,
        }
        self._feedback_timer.start()

    def keyPressEvent(self, e: Any) -> None:
        # ── 편집 모드 ──
        if self._edit_mode:
            if e.key() == Qt.Key_Delete and self._edit_state == "lane_selected":
                # 선택된 lane 끊기
                if self._selected_lane is not None:
                    from_, to = self._selected_lane
                    self.lane_delete_requested.emit(from_, to)
                self._selected_lane = None
                self._edit_state = "ready"
                self.update()
                return
            if e.key() == Qt.Key_Escape:
                # yaw_preview 의 ESC = yaw 유지·위치만 적용
                if self._edit_state == "yaw_preview" and self._yaw_preview is not None:
                    # 원래 노드의 yaw 유지
                    wp_by_name = {w["name"]: w for w in self._waypoints}
                    cur = wp_by_name.get(self._yaw_preview["name"])
                    keep_yaw = float(cur.get("yaw", 0.0)) if cur else 0.0
                    self.node_move_requested.emit(
                        self._yaw_preview["name"],
                        float(self._yaw_preview["new_x"]),
                        float(self._yaw_preview["new_y"]),
                        keep_yaw,
                    )
                    self._yaw_preview = None
                    self._pressed_node = None
                    self._edit_state = "ready"
                    self.update()
                    return
                # 그 외 편집 상태 — 선택/진행 reset.
                # add 모드도 ESC 로 해제 (toolbar 버튼 uncheck 는 카드 측에서 처리).
                # NODE_MOVE_PICKING / _DRAG 도 동일하게 reset (= 이동 취소).
                if self._edit_state != "ready":
                    self._drag_start = None
                    self._drag_current = None
                    self._selected_node = None
                    self._selected_lane = None
                    self._pressed_node = None
                    self._yaw_preview = None
                    self._move_target_node = None
                    self._edit_state = "ready"
                    self.update()
                    return
        # ── 평소 모드 ──
        if e.key() == Qt.Key_Escape and self._drag_start is not None:
            # 진행중 드래그 취소
            self._drag_start = None
            self._drag_current = None
            self.update()
            return
        super().keyPressEvent(e)

    # ─── 편집 모드 상태머신 helpers ───
    def _handle_node_short_click(self, name: str | None) -> None:
        """ADD_LANE 모드에서 노드 클릭 — 1차 선택 → 다른 노드 클릭 시 lane 생성.
        ADD_LANE 모드 진입 후에만 호출된다 (mousePressEvent 에서 분기)."""
        if name is None:
            return
        if self._selected_node is None:
            # 1차 노드 선택
            self._selected_node = name
            self._edit_state = "link_pending"
        elif self._selected_node == name:
            # 같은 노드 → 1차 선택 취소, ADD_LANE 모드는 유지
            self._selected_node = None
            self._edit_state = "add_lane_mode"
        else:
            # 다른 노드 → lane 생성 emit. 모드는 ADD_LANE 유지 (연속 잇기 가능)
            self.lane_create_requested.emit(self._selected_node, name)
            self._selected_node = None
            self._edit_state = "add_lane_mode"
        self._pressed_node = None

    def _enter_yaw_preview(self, end_widget: QPointF) -> None:
        """노드 드래그 release — yaw_preview 상태로 (Task 24)."""
        mx, my = self._widget_to_map(end_widget.x(), end_widget.y())
        self._yaw_preview = {
            "name": self._pressed_node,
            "new_x": mx,
            "new_y": my,
            "end_widget": QPointF(end_widget),
        }
        self._edit_state = "yaw_preview"

    def _commit_yaw_preview(self, click_widget: QPointF) -> None:
        """yaw_preview 단계 클릭 → yaw 확정 emit (Task 24)."""
        if self._yaw_preview is None:
            self._edit_state = "ready"
            return
        end = self._yaw_preview["end_widget"]
        dx = click_widget.x() - end.x()
        dy = click_widget.y() - end.y()
        yaw = math.atan2(-dy, dx) if (dx * dx + dy * dy) ** 0.5 > 1.0 else 0.0
        self.node_move_requested.emit(
            self._yaw_preview["name"],
            float(self._yaw_preview["new_x"]),
            float(self._yaw_preview["new_y"]),
            float(yaw),
        )
        self._yaw_preview = None
        self._pressed_node = None
        self._edit_state = "ready"

    # 편집 모드 더블클릭 — 노드/간선 context menu 요청 signal
    # 카드 측에서 QMenu 띄움 (MapView 는 통신 로직 안 가짐)
    node_double_clicked = pyqtSignal(str)              # name
    lane_double_clicked = pyqtSignal(str, str)         # from, to

    def mouseDoubleClickEvent(self, e: Any) -> None:
        """편집 모드에서만 동작 — 노드/간선 hit 시 signal emit.
        평소 모드는 기존 동작 유지 (super)."""
        if not self._edit_mode:
            super().mouseDoubleClickEvent(e)
            return
        if e.button() != Qt.LeftButton:
            return
        target = self._hit_test(QPointF(e.pos()))
        if target is None:
            return
        if target["kind"] == "node":
            self.node_double_clicked.emit(target["id"])
        elif target["kind"] == "lane":
            from_, to = target["id"]
            self.lane_double_clicked.emit(from_, to)

    # ─── 편집 모드 hit-test (노드 + 간선) ───
    def _hit_test(self, p: QPointF) -> dict | None:
        """widget 좌표 p 가 노드/간선 위인지 판정.
        반환: {"kind": "node", "id": name} 또는 {"kind": "lane", "id": (from, to)},
              아무것도 안 잡히면 None. 노드 우선 (겹치면 노드)."""
        # 노드 — 거리 < NODE_HIT_PX
        for w in self._waypoints:
            wp_pt = self._map_to_widget(w["x"], w["y"])
            dx = p.x() - wp_pt.x()
            dy = p.y() - wp_pt.y()
            if (dx * dx + dy * dy) ** 0.5 < self.NODE_HIT_PX:
                return {"kind": "node", "id": w["name"]}
        # 간선 — 선분과 perpendicular distance, 양 끝 사이에 투영점이 있을 때만
        wp_by_name = {w["name"]: w for w in self._waypoints}
        for ln in self._lanes:
            a = wp_by_name.get(ln.get("from"))
            b = wp_by_name.get(ln.get("to"))
            if not a or not b:
                continue
            pa = self._map_to_widget(a["x"], a["y"])
            pb = self._map_to_widget(b["x"], b["y"])
            d = self._point_seg_distance(p, pa, pb)
            if d is not None and d < self.LANE_HIT_PX:
                return {"kind": "lane", "id": (ln["from"], ln["to"])}
        return None

    def _point_seg_distance(self, p: QPointF, a: QPointF, b: QPointF) -> float | None:
        """점 p 와 선분 a-b 의 거리. 투영점이 선분 안에 있을 때만 값, 밖이면 None."""
        ax, ay = a.x(), a.y()
        bx, by = b.x(), b.y()
        dx, dy = bx - ax, by - ay
        seg_sq = dx * dx + dy * dy
        if seg_sq < 1e-9:
            return None
        t = ((p.x() - ax) * dx + (p.y() - ay) * dy) / seg_sq
        if t < 0 or t > 1:
            return None
        px = ax + t * dx
        py = ay + t * dy
        return ((p.x() - px) ** 2 + (p.y() - py) ** 2) ** 0.5

    def paintEvent(self, _evt: Any) -> None:
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing, True)
        qp.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if not self._map_pixmap.isNull():
            W = self.width(); H = self.height()
            target = QRectF(self._pan.x(), self._pan.y(),
                            W * self._zoom, H * self._zoom)
            qp.drawPixmap(target, self._map_pixmap, QRectF(self._map_pixmap.rect()))
        # 라이브 경로
        if len(self._plan) >= 2:
            pen = QPen(QColor("#00A86B"), 3, Qt.DashLine)
            pen.setDashPattern([4, 4])
            qp.setPen(pen); qp.setBrush(Qt.NoBrush)
            path = QPainterPath(self._map_to_widget(*self._plan[0]))
            for px, py in self._plan[1:]:
                path.lineTo(self._map_to_widget(px, py))
            qp.drawPath(path)
        # 웨이포인트 마커 (graph 모드에서만) — zoom 에 sqrt 비례.
        # 선형이면 확대 시 노드가 화면을 덮어 답답 → 라벨 폰트와 동일하게 sqrt.
        if self._display_mode == 'graph':
            z = math.sqrt(self._zoom)
            # lanes — 회색 선 (마커보다 먼저 그려서 마커가 위에 오게).
            # 편집 모드 hover/selected lane 은 굵게 강조.
            wp_by_name = {w["name"]: w for w in self._waypoints}
            for ln in self._lanes:
                a = wp_by_name.get(ln.get("from"))
                b = wp_by_name.get(ln.get("to"))
                if not a or not b:
                    continue
                pa = self._map_to_widget(a["x"], a["y"])
                pb = self._map_to_widget(b["x"], b["y"])
                lane_id = (ln["from"], ln["to"])
                lane_id_rev = (ln["to"], ln["from"])
                is_selected = self._edit_mode and self._selected_lane in (lane_id, lane_id_rev)
                is_hover = (self._edit_mode and self._hover_target
                            and self._hover_target.get("kind") == "lane"
                            and self._hover_target.get("id") in (lane_id, lane_id_rev))
                if is_selected:
                    qp.setPen(QPen(QColor("#E07B5B"), 4 * z))  # 코랄, 선택 lane (Delete 대상)
                elif is_hover:
                    qp.setPen(QPen(QColor(30, 30, 30), 3 * z))  # 진한 회색, hover
                else:
                    qp.setPen(QPen(QColor(120, 120, 120, 180), 1.5 * z))
                qp.drawLine(pa, pb)
            # route 강조 — 굵은 코랄선
            if self._route and len(self._route) >= 2:
                qp.setPen(QPen(QColor("#E07B5B"), 4 * z))
                for n1, n2 in zip(self._route[:-1], self._route[1:]):
                    a = wp_by_name.get(n1); b = wp_by_name.get(n2)
                    if not a or not b:
                        continue
                    pa = self._map_to_widget(a["x"], a["y"])
                    pb = self._map_to_widget(b["x"], b["y"])
                    qp.drawLine(pa, pb)
            # patrol overlay 준비 — vertex name → 1-based 순번. 없으면 0.
            patrol_index_of: dict[str, int] = {
                n: i for i, n in enumerate(self._patrol_vertices)
            }
            patrol_cur = self._patrol_current_index

            for w in self._waypoints:
                if self._filter is not None and w["name"] not in self._filter:
                    continue
                p = self._map_to_widget(w["x"], w["y"])
                is_current = (w["name"] == self._current_name)
                # patrol 상태 — 0..N-1=대기/진행/방문, N=완료, -1=미진행
                p_idx = patrol_index_of.get(w["name"], None)
                p_is_visited = p_idx is not None and patrol_cur > p_idx
                p_is_now = p_idx is not None and patrol_cur == p_idx
                # 편집 모드 — hover / 선택 노드 (link_pending 1차) 강조
                is_hover_node = (self._edit_mode and self._hover_target
                                 and self._hover_target.get("kind") == "node"
                                 and self._hover_target.get("id") == w["name"])
                is_selected_node = (self._edit_mode
                                    and self._selected_node == w["name"])
                if is_selected_node:
                    r = 7 * z   # 큰 링
                    border_color = "#E07B5B"   # 코랄 — 1차 선택 시그널
                    border_width = 3 * z
                    fill_color = "#FFD9CC"
                elif is_hover_node:
                    r = 5 * z
                    border_color = "#0D4F66"   # 진한 파랑
                    border_width = 3 * z
                    fill_color = "#A8D8E8"
                elif p_is_now:
                    # 현재 진행 중 — 주황 강조
                    r = 7 * z
                    border_color = "#B85C00"
                    border_width = 3 * z
                    fill_color = "#FFA94D"
                elif p_idx is not None and not p_is_visited:
                    # 대기 — 보라 (patrol 대상 식별)
                    r = 5 * z
                    border_color = "#5A2F8A"
                    border_width = 2 * z
                    fill_color = "#C8A8E8"
                elif is_current:
                    r = 5 * z
                    border_color = "#1A6B8A"
                    border_width = 2 * z
                    fill_color = "#00A86B"
                else:
                    r = 3.5 * z
                    border_color = "#1A6B8A"
                    border_width = 2 * z
                    fill_color = "#5BB9E0"
                qp.setPen(QPen(QColor(border_color), border_width))
                qp.setBrush(QBrush(QColor(fill_color)))
                qp.drawEllipse(p, r, r)
                # patrol overlay: 동그라미 안에 번호 (1-based) 또는 X
                if p_idx is not None:
                    overlay_fsize = max(7, int(round(8 * z)))
                    qp.setFont(QFont("", overlay_fsize, QFont.Bold))
                    overlay_rect = QRectF(p.x() - r, p.y() - r, 2 * r, 2 * r)
                    if p_is_visited:
                        qp.setPen(QColor("#1A1A1A"))
                        qp.drawText(overlay_rect, Qt.AlignCenter, "✕")
                    else:
                        # 진행 중 vertex 는 검은 굵은 숫자, 대기는 진한 보라
                        qp.setPen(QColor("#1A1A1A") if p_is_now else QColor("#3A1A6B"))
                        qp.drawText(overlay_rect, Qt.AlignCenter, str(p_idx + 1))
                # 라벨: z 가 이미 sqrt(zoom) 이므로 그대로 사용 (인접 충돌 완화)
                fsize = max(7, int(round(7 * z)))
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
            # 종료 상태면 route 강조 해제
            if ev.get("status") in ("succeeded", "canceled", "aborted", "rejected"):
                self.card._map.set_route(None)
            # nav2 가 active 가 되면 편집 모드 자동 이탈 (Task 27)
            if ev.get("status") in ("active", "pending") and self.card._map._edit_mode:
                self.card._auto_exit_edit_mode_on_nav_active()
        elif t == "waypoints":
            self.card._refresh_list()
        elif t == "route_progress":
            # navigate 진행 중 — 현재 통과 vertex 강조 (vertex 마커 색)
            cur = ev.get("current_vertex")
            if cur:
                self.card._map.set_current(cur)
        elif t == "route_sequence":
            # L1 다익스트라 결과 — vertex sequence 강조선 표시
            seq = ev.get("sequence")
            if isinstance(seq, list) and seq:
                self.card._map.set_route(seq)


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
        # 편집 모드 토글 — graph 모드 한정. nav2 idle 일 때만 진입 가능.
        self._btn_edit = QPushButton("✏ 편집 모드")
        self._btn_edit.setCheckable(True)
        self._btn_edit.setCursor(Qt.PointingHandCursor)
        self._btn_edit.setFixedHeight(28)
        self._btn_edit.setStyleSheet(
            "QPushButton { background: #FFFFFF; color: #1A6B8A; "
            "border: 1.5px solid #5BB9E0; border-radius: 8px; "
            "padding: 0 14px; font-weight: 600; font-size: 12px; }"
            "QPushButton:hover { background: #EAF6FB; }"
            "QPushButton:checked { background: #E07B5B; color: #FFFFFF; "
            "border-color: #E07B5B; }"
        )
        self._btn_edit.clicked.connect(self._on_edit_toggle)

        # 편집 모드 툴바 — ON 일 때만 visible
        self._btn_add_node = self._make_edit_button("+ 노드 생성", "#00A86B")
        self._btn_add_lane = self._make_edit_button("+ 간선 연결", "#00A86B")
        self._btn_add_node.setCheckable(True)   # 모드 진입 토글
        self._btn_add_lane.setCheckable(True)
        self._btn_add_node.clicked.connect(self._on_toggle_add_node)
        self._btn_add_lane.clicked.connect(self._on_toggle_add_lane)
        self._btn_undo = self._make_edit_button("↶ 취소", "#5BB9E0")
        self._btn_auto = self._make_edit_button("⚡ 자동 간선", "#5BB9E0")
        self._btn_reset = self._make_edit_button("⟲ 초기화", "#E07B5B")
        self._btn_snapshot = self._make_edit_button("💾 기본값 갱신", "#1A6B8A")
        self._btn_undo.clicked.connect(self._on_undo)
        self._btn_auto.clicked.connect(self._on_auto_edge)
        self._btn_reset.clicked.connect(self._on_reset)
        self._btn_snapshot.clicked.connect(self._on_snapshot_default)
        self._edit_toolbar = [
            self._btn_add_node, self._btn_add_lane,
            self._btn_undo, self._btn_auto, self._btn_reset, self._btn_snapshot,
        ]
        for b in self._edit_toolbar:
            b.setVisible(False)

        header.addWidget(self._title)
        header.addStretch(1)
        header.addWidget(self._status)
        header.addSpacing(8)
        header.addWidget(self._btn_edit)
        header.addSpacing(8)
        header.addWidget(self._btn_map)
        header.addWidget(self._btn_graph)
        layout.addLayout(header)

        # 편집 모드 toolbar 는 별도 row — 헤더 width 가 옆 카드(카메라 등) 에
        # 영향 주지 않도록 분리. 편집 모드 ON 일 때만 visible.
        self._edit_toolbar_row = QHBoxLayout()
        self._edit_toolbar_row.setContentsMargins(0, 0, 0, 0)
        for b in self._edit_toolbar:
            self._edit_toolbar_row.addWidget(b)
        self._edit_toolbar_row.addStretch(1)
        self._edit_toolbar_container = QWidget()
        self._edit_toolbar_container.setLayout(self._edit_toolbar_row)
        self._edit_toolbar_container.setVisible(False)
        layout.addWidget(self._edit_toolbar_container)

        body = QHBoxLayout()
        self._map = MapView()
        self._map.goal_pose_requested.connect(self._on_goal_pose_requested)
        self._map.initial_pose_requested.connect(self._on_initial_pose_requested)
        # 편집 모드 — Task 22+
        self._map.lane_create_requested.connect(self._on_lane_create)
        self._map.lane_delete_requested.connect(self._on_lane_delete)
        self._map.node_move_requested.connect(self._on_node_move)
        self._map.add_drag_release_requested.connect(self._on_add_drag_release)
        self._map.node_double_clicked.connect(self._on_node_double_clicked)
        self._map.lane_double_clicked.connect(self._on_lane_double_clicked)
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
        self._map_pixmap = self._map._map_pixmap

        QTimer.singleShot(0, self._refresh_list)

        self._dispatcher = _SseDispatcher(self)
        self._sse = _SseThread(f"{control_url}/waypoints/events", self)
        self._sse.event_received.connect(self._dispatcher.handle)
        self._sse.start()

    def _on_toggle_add_node(self) -> None:
        """[+ 노드 생성] 토글 — ADD_NODE 모드 진입/이탈.
        다른 모드 (ADD_LANE) 와 상호배타."""
        if self._btn_add_node.isChecked():
            self._btn_add_lane.setChecked(False)
            self._map._edit_state = "add_node_mode"
            self._map._selected_node = None
            self._map._selected_lane = None
        else:
            if self._map._edit_state in ("add_node_mode", "add_drag"):
                self._map._edit_state = "ready"
        self._map.update()

    def _on_toggle_add_lane(self) -> None:
        """[+ 간선 연결] 토글 — ADD_LANE 모드 진입/이탈."""
        if self._btn_add_lane.isChecked():
            self._btn_add_node.setChecked(False)
            self._map._edit_state = "add_lane_mode"
            self._map._selected_node = None
            self._map._selected_lane = None
        else:
            if self._map._edit_state in ("add_lane_mode", "link_pending"):
                self._map._edit_state = "ready"
                self._map._selected_node = None
        self._map.update()

    def _make_edit_button(self, text: str, accent: str) -> QPushButton:
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedHeight(28)
        b.setStyleSheet(
            f"QPushButton {{ background: #FFFFFF; color: {accent}; "
            f"border: 1.5px solid {accent}; border-radius: 8px; "
            f"padding: 0 10px; font-weight: 600; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {accent}; color: white; }}"
            f"QPushButton:disabled {{ color: #B0B0B0; border-color: #D0D0D0; }}"
        )
        return b

    def _auto_exit_edit_mode_on_nav_active(self) -> None:
        """SSE goal_status: active 수신 → 편집 모드 자동 이탈 + 알림.
        진행 중 selection / drag / yaw_preview / add 모드 모두 reset."""
        self._map._edit_mode = False
        self._map._edit_state = "ready"
        self._map._selected_node = None
        self._map._selected_lane = None
        self._map._yaw_preview = None
        self._map._pressed_node = None
        self._map._hover_target = None
        self._map._move_target_node = None
        self._btn_edit.setChecked(False)
        self._btn_add_node.setChecked(False)
        self._btn_add_lane.setChecked(False)
        self._refresh_edit_toolbar()
        self._map.update()
        # 알림 — SSE thread 에서 직접 dialog 띄우면 위험. queued connection 으로.
        QTimer.singleShot(0, lambda: QMessageBox.information(
            self, "편집 종료", "이동이 시작되어 편집 모드가 종료되었어요."
        ))

    def _refresh_edit_toolbar(self) -> None:
        """편집 모드 ON/OFF 에 맞춰 툴바 row + 개별 버튼 visibility 토글.
        row container 를 통째로 숨겨 옆 카드(카메라 등) width 에 영향 안 가게."""
        on = self._map._edit_mode
        for b in self._edit_toolbar:
            b.setVisible(on)
        self._edit_toolbar_container.setVisible(on)

    def _on_edit_toggle(self) -> None:
        """편집 모드 토글 — 진입 시 health 호출해 nav_active 검사.
        nav2 이동 중이면 진입 거부 + 토스트."""
        import httpx
        if not self._btn_edit.isChecked():
            # OFF
            self._map._edit_mode = False
            self._map._edit_state = "ready"
            self._map._selected_node = None
            self._map._selected_lane = None
            self._map._yaw_preview = None
            self._map._hover_target = None
            self._map._move_target_node = None
            self._btn_add_node.setChecked(False)
            self._btn_add_lane.setChecked(False)
            self._refresh_edit_toolbar()
            self._map.update()
            return
        try:
            r = httpx.get(f"{self._control_url}/waypoints/health", timeout=2.0)
            nav_active = bool(r.json().get("nav_active", False)) if r.status_code == 200 else False
        except httpx.HTTPError:
            nav_active = False
        if nav_active:
            QMessageBox.information(self, "편집 불가",
                                    "이동 중에는 편집할 수 없어요. 도착 후 다시 시도하세요.")
            self._btn_edit.setChecked(False)
            return
        self._map._edit_mode = True
        self._refresh_edit_toolbar()
        self._map.update()

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

    def update_patrol(self, patrol: dict | None) -> None:
        """``/gogoping/state`` 의 ``patrol`` 필드를 받아 시각화 갱신.

        patrol = {"vertices": [...], "current_index": int} 또는 None (미진행).
        """
        if not patrol or not isinstance(patrol, dict):
            self._map.set_patrol(None, -1)
            return
        verts = patrol.get("vertices") or []
        idx = patrol.get("current_index", -1)
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = -1
        verts_list = list(verts)
        # 완료 (idx >= N) 또는 idle (idx < 0) → overlay 해제, 원래 상태로 복원
        if idx < 0 or idx >= len(verts_list):
            self._map.set_patrol(None, -1)
            return
        self._map.set_patrol(verts_list, idx)

    def _refresh_list(self) -> None:
        import httpx
        try:
            r = httpx.get(f"{self._control_url}/waypoints", timeout=2.0)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError:
            return
        self._map.set_waypoints(data["waypoints"])
        self._map.set_lanes(data.get("lanes") or [])
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
        """좌클릭 = graph navigate (다익스트라 → 실제 이동).
        직접 NavigateToPose (/waypoints/goto) 는 더 이상 안 씀."""
        name = item.data(Qt.UserRole)
        self._on_graph_navigate(name)

    def _on_list_context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        name = item.data(Qt.UserRole)
        menu = QMenu(self._list)
        route_act = QAction(f"경로 미리보기: → '{name}'", menu)
        route_act.triggered.connect(lambda: self._on_preview_route(name))
        navigate_act = QAction(f"graph navigate → '{name}'", menu)
        navigate_act.triggered.connect(lambda: self._on_graph_navigate(name))
        clear_act = QAction("경로 강조 해제", menu)
        clear_act.triggered.connect(lambda: self._map.set_route(None))
        delete_act = QAction(f"🗑  '{name}' 삭제", menu)
        delete_act.triggered.connect(lambda: self._on_delete(name))
        menu.addAction(route_act)
        menu.addAction(navigate_act)
        menu.addAction(clear_act)
        menu.addSeparator()
        menu.addAction(delete_act)
        menu.exec_(self._list.viewport().mapToGlobal(pos))

    def _on_preview_route(self, name: str) -> None:
        """다익스트라 결과만 받아서 강조선 표시 (로봇 안 움직임)."""
        import httpx
        try:
            r = httpx.post(f"{self._control_url}/waypoints/route",
                           json={"name": name}, timeout=2.0)
        except httpx.HTTPError as e:
            QMessageBox.critical(self, "통신 오류", str(e))
            return
        if r.status_code != 200:
            QMessageBox.warning(self, "경로 없음", r.json().get("detail", r.text))
            return
        seq = r.json().get("vertex_sequence") or []
        self._map.set_route(seq)

    def _on_graph_navigate(self, name: str) -> None:
        """장소 클릭 → FSM GOTO 진입 (SetGoal.srv → state GOTO 전이).

        /waypoints/navigate(graph_router action 직행)는 robot 이동은 하지만 FSM 을
        안 거쳐 state 가 IDLE 에 머문다 → proximity/YOLO(person·obstacle 감지)가 안 켜짐.
        FSM trigger 를 거치는 /api/gogoping/goto_vertex 로 호출해 state=GOTO 전이까지 발생시킨다.
        """
        import httpx
        try:
            httpx.post(f"{self._control_url}/api/gogoping/goto_vertex",
                       json={"name": name}, timeout=2.0)
        except httpx.HTTPError:
            pass

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
        """MapView 의 클릭-드래그 → 가장 가까운 vertex 를 찾아 graph_router 로 위임.

        운영 정책 (2026-05-28): vertex 안 거치는 자유 Nav2 goal 비활성화 — 실 환경의
        admin UI 사용 패턴과 일치시키기 위해 임의 (x,y) 좌표 직접 navigation 금지.
        클릭-드래그하면 가장 가까운 vertex 로 graph_router NavigateToVertex chain 호출.
        """
        import httpx
        import math
        # 등록된 waypoints 중 가장 가까운 vertex 선택
        if not self._map._waypoints:
            return
        nearest = min(
            self._map._waypoints,
            key=lambda w: math.hypot(w["x"] - x, w["y"] - y),
        )
        try:
            # 리스트 클릭과 동일하게 FSM GOTO 경로 — state=GOTO 전이로 proximity/YOLO 활성화.
            httpx.post(
                f"{self._control_url}/api/gogoping/goto_vertex",
                json={"name": nearest["name"]}, timeout=2.0,
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

    # ─── 편집 모드 endpoint 핸들러 (Task 22+) ───
    def _on_lane_create(self, from_: str, to: str) -> None:
        """노드 2 클릭 → POST /waypoints/lanes."""
        import httpx
        try:
            r = httpx.post(f"{self._control_url}/waypoints/lanes",
                           json={"from": from_, "to": to}, timeout=2.0)
            if r.status_code == 409:
                return   # 이미 있음 — 잘못 누른 거니 무음
            if r.status_code != 200:
                QMessageBox.warning(self, "간선 생성 실패", r.text)
        except httpx.HTTPError as e:
            QMessageBox.warning(self, "통신 오류", str(e))

    def _on_lane_delete(self, from_: str, to: str) -> None:
        """Delete 키 → DELETE /waypoints/lanes."""
        import httpx
        try:
            httpx.request("DELETE", f"{self._control_url}/waypoints/lanes",
                          json={"from": from_, "to": to}, timeout=2.0)
        except httpx.HTTPError as e:
            QMessageBox.warning(self, "통신 오류", str(e))

    # ─── Task 31: 더블클릭/우클릭 context menu ───
    def _on_node_double_clicked(self, name: str) -> None:
        """노드 더블클릭 / 우클릭 → 메뉴: [이름 변경] [이동] [삭제]."""
        menu = QMenu(self)
        rename_act = QAction(f"✏  '{name}' 이름 변경", menu)
        move_act = QAction(f"🚶  '{name}' 이동", menu)
        delete_act = QAction(f"🗑  '{name}' 삭제", menu)
        rename_act.triggered.connect(lambda: self._on_rename_node(name))
        move_act.triggered.connect(lambda: self._on_move_node_start(name))
        delete_act.triggered.connect(lambda: self._on_delete_node(name))
        menu.addAction(rename_act)
        menu.addAction(move_act)
        menu.addAction(delete_act)
        from PyQt5.QtGui import QCursor
        menu.exec_(QCursor.pos())

    def _on_lane_double_clicked(self, from_: str, to: str) -> None:
        """간선 더블클릭 → 메뉴: [삭제]."""
        menu = QMenu(self)
        delete_act = QAction(f"🗑  '{from_} ↔ {to}' 끊기", menu)
        delete_act.triggered.connect(lambda: self._on_lane_delete(from_, to))
        menu.addAction(delete_act)
        from PyQt5.QtGui import QCursor
        menu.exec_(QCursor.pos())

    def _on_rename_node(self, name: str) -> None:
        """이름 입력 prompt → PATCH /waypoints/{name}/rename."""
        from PyQt5.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(self, "이름 변경",
                                            f"'{name}' 의 새 이름:", text=name)
        if not ok or not new_name.strip() or new_name.strip() == name:
            return
        import httpx
        try:
            r = httpx.patch(f"{self._control_url}/waypoints/{name}/rename",
                            json={"new_name": new_name.strip()}, timeout=2.0)
            if r.status_code == 409:
                QMessageBox.warning(self, "이름 중복",
                                    "이미 같은 이름의 노드가 있어요.")
            elif r.status_code != 200:
                QMessageBox.warning(self, "이름 변경 실패",
                                    f"HTTP {r.status_code}: {r.text[:200]}")
        except httpx.HTTPError as e:
            QMessageBox.warning(self, "통신 오류", str(e))

    def _on_delete_node(self, name: str) -> None:
        """삭제 확인 → DELETE /waypoints/{name}.
        cascade lane 정보가 응답에 있으면 표시."""
        reply = QMessageBox.question(
            self, "노드 삭제",
            f"'{name}' 을 삭제할까요?\n연결된 간선도 함께 제거돼요.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        import httpx
        try:
            r = httpx.delete(f"{self._control_url}/waypoints/{name}", timeout=2.0)
            if r.status_code == 404:
                return   # 이미 없음 — silent
            if r.status_code == 409:
                QMessageBox.warning(self, "삭제 불가", r.json().get("detail", r.text))
                return
            if r.status_code != 200:
                QMessageBox.warning(self, "삭제 실패", r.text)
                return
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            cascaded = body.get("cascaded_lanes", [])
            if cascaded:
                QMessageBox.information(
                    self, "삭제 완료",
                    f"노드 + 연결된 간선 {len(cascaded)}개 제거됨.",
                )
        except httpx.HTTPError as e:
            QMessageBox.warning(self, "통신 오류", str(e))

    def _on_move_node_start(self, name: str) -> None:
        """[이동] 메뉴 → 맵 위 클릭+드래그로 새 위치/방향 입력 모드 진입.
        클릭 = 새 위치, 드래그 방향 = yaw. Esc 로 취소."""
        # 노드 하이라이트 (코랄 큰 링) — _selected_node 가 그림
        self._map._selected_node = name
        self._map._move_target_node = name
        self._map._edit_state = "node_move_picking"
        # 진행 중 잔재 정리
        self._map._drag_start = None
        self._map._drag_current = None
        self._map.setFocus(Qt.MouseFocusReason)
        self._map.update()

    def _on_node_move(self, name: str, x: float, y: float, yaw: float) -> None:
        """노드 이동 → PATCH /waypoints/{name}."""
        import httpx
        try:
            httpx.patch(f"{self._control_url}/waypoints/{name}",
                        json={"x": x, "y": y, "yaw": yaw}, timeout=2.0)
        except httpx.HTTPError as e:
            QMessageBox.warning(self, "통신 오류", str(e))

    def _on_add_drag_release(self, start_widget: QPointF, end_widget: QPointF) -> None:
        """빈 곳 드래그 release → 이름 팝업 → POST /waypoints/click.
        성공 시 ADD_NODE 모드 자동 해제 (한 번 추가하면 모드 빠짐 — 실수 방지)."""
        from PyQt5.QtWidgets import QInputDialog
        mx, my = self._map._widget_to_map(start_widget.x(), start_widget.y())
        dx = end_widget.x() - start_widget.x()
        dy = end_widget.y() - start_widget.y()
        yaw = math.atan2(-dy, dx) if (dx * dx + dy * dy) ** 0.5 > 1.0 else 0.0
        name, ok = QInputDialog.getText(self, "노드 추가", "이름:")
        if not ok or not name.strip():
            return
        import httpx
        try:
            r = httpx.post(f"{self._control_url}/waypoints/click",
                           json={"name": name.strip(), "x": mx, "y": my, "yaw": yaw},
                           timeout=2.0)
            if r.status_code == 409:
                QMessageBox.warning(self, "이름 중복", "이미 같은 이름의 노드가 있어요.")
                return
        except httpx.HTTPError as e:
            QMessageBox.warning(self, "통신 오류", str(e))
            return
        # 성공 — ADD_NODE 모드 해제
        self._btn_add_node.setChecked(False)
        self._map._edit_state = "ready"
        self._map.update()

    # ─── 편집 모드 헤더 툴바 핸들러 (Task 26) ───
    def _on_undo(self) -> None:
        """[↶ 취소] — 가장 최근 추가한 노드 한 개만 제거."""
        import httpx
        try:
            r = httpx.post(f"{self._control_url}/waypoints/undo", timeout=2.0)
            if r.status_code == 408:
                QMessageBox.information(self, "취소", "되돌릴 작업이 없어요.")
            elif r.status_code == 409:
                QMessageBox.warning(self, "취소 불가",
                                    "이 노드에 이미 간선이 잇혀 있어요. 간선 먼저 끊으세요.")
            elif r.status_code != 200:
                QMessageBox.warning(self, "취소 실패", r.text)
        except httpx.HTTPError as e:
            QMessageBox.warning(self, "통신 오류", str(e))

    # 자동 간선 dialog 의 안전 범위 (m).
    _AUTO_EDGE_MIN = 0.1
    _AUTO_EDGE_MAX = 50.0
    _AUTO_EDGE_DEFAULT = 1.5

    def _on_auto_edge(self) -> None:
        """[⚡ 자동 간선] — threshold 입력 dialog + replace 선택 → 일괄 lane 생성.
        모든 단계에서 예외를 잡아 admin UI 가 죽지 않도록 한다."""
        from PyQt5.QtWidgets import QInputDialog
        try:
            wps = self._map._waypoints
            if len(wps) < 2:
                QMessageBox.information(self, "자동 간선", "노드가 2개 이상이어야 해요.")
                return

            threshold, ok = QInputDialog.getDouble(
                self, "자동 간선",
                f"거리 threshold (m). 기본값 {self._AUTO_EDGE_DEFAULT}m.",
                self._AUTO_EDGE_DEFAULT,
                self._AUTO_EDGE_MIN, self._AUTO_EDGE_MAX, 2,
            )
            if not ok:
                return
            replace = QMessageBox.question(
                self, "자동 간선",
                "기존 간선을 모두 교체할까요?\n예: 기존 제거 후 새로 생성\n아니오: 기존 보존 + 새 쌍만 추가",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) == QMessageBox.Yes
            import httpx
            try:
                r = httpx.post(f"{self._control_url}/waypoints/lanes/auto",
                               json={"threshold": threshold, "replace_existing": replace},
                               timeout=10.0)
            except httpx.HTTPError as e:
                QMessageBox.warning(self, "통신 오류", str(e))
                return
            if r.status_code == 200:
                body = r.json()
                added = body.get('added', 0)
                skipped = body.get('skipped', 0)
                # reload_graph 부분 실패 (server 가 yaml 은 썼지만 ROS reload 못 함)
                # — UI 에 표시
                extra = ""
                if body.get('graph_reloaded') is False:
                    extra = f"\n\n⚠ 실시간 반영 실패 — graph_router_node 재시작 필요:\n{body.get('detail', '')}"
                QMessageBox.information(
                    self, "자동 간선",
                    f"추가: {added}개 / 건너뜀: {skipped}개{extra}",
                )
            else:
                QMessageBox.warning(self, "자동 간선 실패",
                                    f"HTTP {r.status_code}: {r.text[:300]}")
        except Exception as e:
            # 예상치 못한 예외도 dialog 로 — admin UI crash 방지
            QMessageBox.critical(self, "자동 간선 오류", f"{type(e).__name__}: {e}")

    def _on_reset(self) -> None:
        """[⟲ 초기화] — default snapshot 으로 working 덮어쓰기."""
        reply = QMessageBox.question(
            self, "초기화",
            "편집 결과를 버리고 기본값으로 복구합니다.\n되돌릴 수 없어요. 계속할까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        import httpx
        try:
            r = httpx.post(f"{self._control_url}/waypoints/reset", timeout=5.0)
            if r.status_code == 409:
                QMessageBox.warning(self, "초기화 불가",
                                    "기본값 파일이 없어요. [기본값 갱신] 으로 먼저 만드세요.")
            elif r.status_code != 200:
                QMessageBox.warning(self, "초기화 실패", r.text)
        except httpx.HTTPError as e:
            QMessageBox.warning(self, "통신 오류", str(e))

    def _on_snapshot_default(self) -> None:
        """[💾 기본값 갱신] — 현재 working 을 default snapshot 으로 동결."""
        wps_count = len(self._map._waypoints)
        lanes_count = len(self._map._lanes)
        reply = QMessageBox.question(
            self, "기본값 갱신",
            f"현재 노드 {wps_count}개 / 간선 {lanes_count}개를 기본값으로 동결합니다.\n"
            "이후 [⟲ 초기화] 누르면 이 상태로 복구돼요. 계속할까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        import httpx
        try:
            r = httpx.post(f"{self._control_url}/waypoints/snapshot-default",
                           timeout=5.0)
            if r.status_code == 200:
                QMessageBox.information(self, "기본값 갱신", "현재 상태가 기본값으로 저장됐어요.")
            else:
                QMessageBox.warning(self, "기본값 갱신 실패", r.text)
        except httpx.HTTPError as e:
            QMessageBox.warning(self, "통신 오류", str(e))

    def closeEvent(self, e: Any) -> None:
        self._sse.stop()
        self._sse.wait(2000)
        super().closeEvent(e)
