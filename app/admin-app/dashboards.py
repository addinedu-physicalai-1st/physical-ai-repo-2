"""세 로봇 대시보드. 모두 가짜 데이터 + QTimer 로 살아있는 느낌만 흉내낸다.

이모지 대신 Icon / IconText / TaskQueue 의 아이콘 kind 를 쓴다.
"""

from __future__ import annotations

import math
import os
import random

from PyQt5.QtCore import QEvent, QObject, Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# QWebEngineView 는 별도 패키지 (PyQtWebEngine) — 미설치 환경에선 placeholder 로 fallback.
try:
    from PyQt5.QtWebEngineWidgets import (  # type: ignore[import-not-found]
        QWebEnginePage,
        QWebEngineSettings,
        QWebEngineView,
    )

    _HAS_WEBENGINE = True

    class _DevPermissivePage(QWebEnginePage):
        """Accept self-signed certs on localhost (Vite mkcert) so the admin viewer
        can load `https://localhost:5173/?embed=openarm` without manual CA install.

        Only swallows cert errors whose URL is localhost / 127.0.0.1 — production
        HTTPS errors still bubble up.
        """

        def certificateError(self, error):  # type: ignore[override]
            try:
                url = error.url().host()
            except Exception:
                url = ""
            return url in ("localhost", "127.0.0.1", "")

except ImportError:
    QWebEngineView = None  # type: ignore[assignment, misc]
    QWebEnginePage = None  # type: ignore[assignment, misc]
    QWebEngineSettings = None  # type: ignore[assignment, misc]
    _DevPermissivePage = None  # type: ignore[assignment, misc]
    _HAS_WEBENGINE = False


def _tune_webengine_view(view: "QWebEngineView") -> None:
    """Hardware WebGL / compositor for embedded Three.js (GPU when Chromium allows)."""
    if QWebEngineSettings is None:
        return
    try:
        s = view.settings()
        s.setAttribute(QWebEngineSettings.WebGLEnabled, True)
        s.setAttribute(QWebEngineSettings.Accelerated2dCanvasEnabled, True)
        s.setAttribute(QWebEngineSettings.ScrollAnimatorEnabled, False)
        # Qt 5.14+ — request WebGL2 when available (falls back to WebGL1).
        webgl2 = getattr(QWebEngineSettings, "WebGL2Enabled", None)
        if webgl2 is not None:
            s.setAttribute(webgl2, True)
        # https://localhost:5173 compare page fetches http://127.0.0.1:<data-port>
        for attr in (
            "LocalContentCanAccessRemoteUrls",
            "AllowRunningInsecureContent",
        ):
            key = getattr(QWebEngineSettings, attr, None)
            if key is not None:
                s.setAttribute(key, True)
    except Exception:  # noqa: BLE001
        pass


class _CompareDataServer:
    """Localhost HTTP server (daemon thread) serving the compare payload as JSON.

    Legacy: compare popup may fetch via `?data-port=`. PyQt path injects JSON
    directly and does not use this server.
    A hash-encoded URL turned out too large (~100KB+ base64) for xdg-open / address
    bar paste, so the JSON payload lives here on a separate `http://localhost:NNNN`
    socket. The page URL just carries `?data-port=NNNN` and fetches the data.

    Chrome treats `http://localhost` as a Potentially-Trustworthy Origin so the
    HTTPS-from-vite page can fetch the HTTP localhost endpoint without mixed-
    content blocking. (Firefox is stricter; user may need Chrome.)
    """

    def __init__(self, payload_bytes: bytes) -> None:
        import http.server
        import socket
        import threading

        # Auto-assign a free port — start a temporary socket, read its bound port,
        # close, then bind the real server to the same number. Tiny race window
        # but acceptable for a single-user admin tool.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        self.port: int = s.getsockname()[1]
        s.close()

        body = payload_bytes

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                self.send_response(200)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    pass

            def log_message(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002, D401
                pass  # silence default access log

        self._server = http.server.HTTPServer(("127.0.0.1", self.port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:  # noqa: BLE001
            pass


from theme import COLORS, ROBOTS
from widgets import (
    BatteryBar,
    Card,
    CameraView,
    CompassDial,
    GripperIndicator,
    Icon,
    IconText,
    Joint,
    JointPanel,
    MetricRow,
    StatChip,
    StatusBadge,
    TaskQueue,
    soften,
)
from widgets.camera_widget import CameraStreamView, WebRTCStreamView
from widgets.waypoint_map_card import WaypointMapCard


# --------------------------------------------------------------------------
# 공용 헤더
# --------------------------------------------------------------------------


class RobotHeader(QWidget):
    """대시보드 상단 — 로봇 아이콘, 이름, 한 줄 설명, 상태 뱃지."""

    def __init__(self, robot_key: str, parent=None):
        super().__init__(parent)
        meta = ROBOTS[robot_key]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        avatar = QWidget()
        avatar.setFixedSize(64, 64)
        avatar.setStyleSheet(
            f"background: {meta['color_soft']}; border-radius: 32px;"
        )
        avatar_lay = QVBoxLayout(avatar)
        avatar_lay.setContentsMargins(0, 0, 0, 0)
        icon = Icon(meta["icon"], size=36, color=meta["color"])
        avatar_lay.addWidget(icon, 0, Qt.AlignCenter)
        lay.addWidget(avatar)

        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(meta["name"])
        title.setObjectName("hero")
        sub = QLabel(meta["tagline"])
        sub.setObjectName("heroSub")
        text.addWidget(title)
        text.addWidget(sub)
        lay.addLayout(text)
        lay.addStretch(1)

        self.badge = StatusBadge("정상 작동", COLORS["success"])
        lay.addWidget(self.badge)


# --------------------------------------------------------------------------
# NoriArm — 놀이·정리정돈
# --------------------------------------------------------------------------


class NoriArmDashboard(QWidget):
    NAME = "noriarm"
    JOINTS = [
        Joint("Base",     12.4, -180, 180),
        Joint("Shoulder", -34.0, -120, 120),
        Joint("Elbow",     58.7, -150, 150),
        Joint("Wrist1",   -22.1, -180, 180),
        Joint("Wrist2",    91.0, -180, 180),
        Joint("Wrist3",   -7.5, -180, 180),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        meta = ROBOTS[self.NAME]
        accent = meta["color"]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        self.header = RobotHeader(self.NAME)
        outer.addWidget(self.header)

        main_lay = QHBoxLayout()
        outer.addLayout(main_lay, 1)

        grid = QGridLayout()
        grid.setSpacing(14)
        main_lay.addLayout(grid, 1)

        # 현재 작업
        self.task_card = Card("지금 하는 일")
        self.task_card.set_watermark("📦")
        task_title_row = QHBoxLayout()
        task_title_row.setSpacing(10)
        task_title_row.addWidget(Icon("block", size=28, color=accent))
        self.task_title = QLabel("블록 정리하기")
        self.task_title.setObjectName("hero")
        task_title_row.addWidget(self.task_title)
        task_title_row.addStretch(1)
        self.task_sub = QLabel("쌓여있는 블록을 색깔별로 분류해서 박스에 담는 중")
        self.task_sub.setObjectName("heroSub")
        self.task_sub.setWordWrap(True)
        self.task_progress = QProgressBar()
        self.task_progress.setValue(48)
        self.task_progress.setFormat("진행률 %p%")
        self.task_progress.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {accent}; }}"
        )
        self.task_card.body.addLayout(task_title_row)
        self.task_card.body.addWidget(self.task_sub)
        self.task_card.body.addSpacing(4)
        self.task_card.body.addWidget(self.task_progress)

        # 그리퍼
        gripper_card = Card("그리퍼")
        gripper_card.set_watermark("🦾")
        self.gripper = GripperIndicator(accent)
        gripper_card.body.addWidget(self.gripper, 0, Qt.AlignCenter)

        # 시스템
        system_card = Card("시스템 상태")
        system_card.set_watermark("⚙️")
        system_card.body.addWidget(_battery_row(self))
        self.cpu_row = MetricRow("CPU", "23%")
        self.temp_row = MetricRow("관절 온도", "42 °C")
        self.uptime_row = MetricRow("가동 시간", "3시간 12분")
        self.mode_row = QWidget()
        mr = QHBoxLayout(self.mode_row)
        mr.setContentsMargins(0, 0, 0, 0)
        mr.setSpacing(8)
        mr.addWidget(QLabel("모드"))
        mr.addStretch(1)
        mr.addWidget(IconText("robot", "자동", size=14,
                              color=accent, bold=True, font_pt=12))
        for w in (self.cpu_row, self.temp_row, self.uptime_row, self.mode_row):
            system_card.body.addWidget(w)

        # 관절
        joint_card = Card("관절 각도")
        self.joints = JointPanel(self.JOINTS, accent)
        joint_card.body.addWidget(self.joints)

        # 작업 큐
        queue_card = Card("오늘의 일정")
        queue_card.set_watermark("📋")
        self.queue = TaskQueue(accent)
        self.queue.set_tasks([
            ("block",     "블록 정리하기"),
            ("palette",   "그림 도구 정돈"),
            ("book",      "책 책장에 꽂기"),
            ("food",      "간식 시간 보조"),
            ("ball",      "장난감 살균함에 정리"),
        ])
        queue_card.body.addWidget(self.queue)

        grid.addWidget(self.task_card,  0, 0, 1, 2)
        grid.addWidget(gripper_card,    0, 2, 1, 1)
        grid.addWidget(joint_card,      1, 0, 1, 2)
        grid.addWidget(system_card,     1, 2, 1, 1)
        grid.addWidget(queue_card,      2, 0, 1, 2)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        self._tick = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(80)

    def _on_tick(self) -> None:
        self._tick += 1

        angles = []
        for i, j in enumerate(self.JOINTS):
            wobble = math.sin(self._tick * 0.04 + i) * 6
            angles.append(j.angle + wobble)
        self.joints.update_angles(angles)

        gripper = (math.sin(self._tick * 0.03) + 1) / 2
        self.gripper.set_open(gripper)

        if self._tick % 25 == 0:
            cur = self.task_progress.value()
            self.task_progress.setValue((cur + 1) % 101)

        if self._tick % 12 == 0:
            self.cpu_row.set_value(f"{random.randint(18, 32)}%")
            self.temp_row.set_value(f"{random.randint(40, 46)} °C")


# --------------------------------------------------------------------------
# 디버그 사이드 서랍 — GogoPing 우측에 접고 펼치는 패널
# --------------------------------------------------------------------------


class DebugDrawer(QWidget):
    """본문 우측에 붙는 접힘/펼침 사이드 서랍. 좌측 토글 버튼 + 우측 패널 컨테이너.

    panel 안에는 DebugStatePanel / BatteryDebugSlider / PoseDebugPanel / NavDebugLogCard
    4개가 세로 stack. 토글 버튼 (◂/▸) 클릭 시 panel 만 show/hide — 버튼 자체는 항상
    노출되어 다시 펼칠 수 있다. 초기 상태: 펼침 (open=True).
    """

    PANEL_WIDTH = 340  # NavDebugLogCard 의 monospace 로그가 너무 좁지 않게 살짝 ↑
    TOGGLE_WIDTH = 36

    def __init__(self, debug_panel, battery_debug, pose_debug, nav_debug_log, parent=None):
        super().__init__(parent)
        self.setObjectName("debugDrawer")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 토글 버튼 — 강조색 배경 + 흰 글씨 + 세로 "DEBUG" 라벨. 항상 보임.
        # 텍스트 구성: "◂\nD\nE\nB\nU\nG"  (펼침 상태 — 화살표가 닫는 방향을 가리킴)
        self.toggle_btn = QPushButton(self._toggle_text(opened=True))
        self.toggle_btn.setFixedWidth(self.TOGGLE_WIDTH)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        accent = COLORS["warning"]
        accent_hover = soften(accent, 0.80)
        self.toggle_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: {accent};
                border: none;
                border-top-left-radius: 12px;
                border-bottom-left-radius: 12px;
                color: white;
                font-size: 11pt;
                font-weight: 900;
                letter-spacing: 1px;
                padding: 10px 4px;
                text-align: center;
            }}
            QPushButton:hover {{ background: {accent_hover}; }}
            QPushButton:pressed {{ background: {accent}; }}
            """
        )
        self.toggle_btn.clicked.connect(self._toggle)
        lay.addWidget(self.toggle_btn)

        # panel 컨테이너 — 3개 디버그 위젯 세로 stack
        self.panel = QWidget()
        self.panel.setFixedWidth(self.PANEL_WIDTH)
        panel_lay = QVBoxLayout(self.panel)
        panel_lay.setContentsMargins(8, 0, 0, 0)
        panel_lay.setSpacing(10)
        panel_lay.addWidget(debug_panel)
        panel_lay.addWidget(battery_debug)
        panel_lay.addWidget(pose_debug)
        panel_lay.addWidget(nav_debug_log, stretch=1)   # 로그가 남는 공간 차지
        lay.addWidget(self.panel)

        self._open = True

    def _toggle(self) -> None:
        self._open = not self._open
        self.panel.setVisible(self._open)
        self.toggle_btn.setText(self._toggle_text(opened=self._open))

    @staticmethod
    def _toggle_text(opened: bool) -> str:
        """세로 라벨 — 화살표 + DEBUG 5글자.

        opened=True 면 ▸ (접기), False 면 ◂ (펼치기).
        """
        arrow = "▸" if opened else "◂"
        return f"{arrow}\nD\nE\nB\nU\nG"


# --------------------------------------------------------------------------
# GogoPing — 자율주행
# --------------------------------------------------------------------------


class GogoPingDashboard(QWidget):
    NAME = "gogoping"

    def __init__(self, parent=None, stream_client=None):
        super().__init__(parent)
        self._stream_client = stream_client

        # 디버그 위젯 3종 — DebugDrawer 가 담을 예정. dashboard attribute 로 노출되어
        # main.py 의 signal connect 가 self.dashboard.debug_panel 형태로 접근.
        from widgets.battery_debug_slider import BatteryDebugSlider
        from widgets.debug_state_panel import DebugStatePanel
        from widgets.nav_debug_log_card import NavDebugLogCard
        from widgets.pose_debug_panel import PoseDebugPanel
        self.debug_panel = DebugStatePanel()
        self.battery_debug = BatteryDebugSlider()
        self.pose_debug = PoseDebugPanel()
        self.nav_debug_log = NavDebugLogCard()

        # 창이 짧을 때 teleop 영역이 잘리지 않도록 전체를 스크롤 영역으로 감싼다.
        # 폭은 늘 채우고, 세로 컨텐츠가 창 높이를 초과하면 스크롤바가 등장한다.
        scroll = QScrollArea(self)
        scroll.setObjectName("dashScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 배경이 비치도록 viewport 투명 처리
        scroll.setStyleSheet(
            "QScrollArea#dashScroll, QScrollArea#dashScroll > QWidget > QWidget {"
            "  background: transparent;"
            "}"
        )

        # 우측 디버그 사이드 서랍 — 토글 시 panel 접힘/펼침
        self.debug_drawer = DebugDrawer(
            self.debug_panel, self.battery_debug, self.pose_debug,
            self.nav_debug_log,
        )

        # host: 좌측 스크롤 (대시보드 콘텐츠) + 우측 서랍
        host_lay = QHBoxLayout(self)
        host_lay.setContentsMargins(0, 0, 0, 0)
        host_lay.setSpacing(0)
        host_lay.addWidget(scroll, 1)
        host_lay.addWidget(self.debug_drawer, 0)

        content = QWidget()
        content.setObjectName("dashContent")
        scroll.setWidget(content)

        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 20, 28, 24)
        outer.setSpacing(14)

        # 본문 상단 chip 행은 제거 — 배터리는 TopBar 로 통합 (main.py).
        # 다른 chip (CPU/LiDAR/위치신뢰도/오늘주행) 은 mock 데이터라 함께 제거.
        meta = ROBOTS[self.NAME]

        from widgets.lidar_scan_view import LidarScanView
        from widgets.odom_compact import OdomCompact

        control_url = os.environ.get(
            "PINGDER_CONTROL_URL", "http://localhost:8000",
        )

        # Teleop / CameraPan client + card — 먼저 생성.
        from services.teleop_client import TeleopClient
        from widgets.teleop_card import TeleopCard
        self.teleop_client = TeleopClient()
        self.teleop_card = TeleopCard(
            send_cmd_vel=self.teleop_client.post_cmd_vel,
            get_health=self.teleop_client.get_health,
            control_url=control_url,
        )

        from services.camera_pan_client import CameraPanClient
        from widgets.camera_pan_card import CameraPanCard
        self.camera_pan_client = CameraPanClient(base_url=control_url)
        self.camera_pan_card = CameraPanCard(
            send_cmd=self.camera_pan_client.post_cmd,
            get_health=self.camera_pan_client.get_health,
        )

        # ── 좌우 컬럼 1:1 강제 — grid 의 columnStretch 보다 outer QHBoxLayout 이 더 신뢰 가능
        # 좌측: 카메라 / Teleop·Pan / ODOM·MAP (세로 3 stack)
        # 우측: 맵 (큰) / LiDAR (작음)

        # 좌측 컬럼 — 각 카드 minimumHeight 명시해 페이지 세로 확장 (스크롤 허용).
        self.camera_card = Card("전방 카메라")
        # GogoPing 은 D435 + WebRTC (1080p H.264) 로 전환 — QWebEngineView 가
        # control-service 의 HTTP mirror (/admin-embed/?embed=gogoping-video) 임베드.
        # 다른 로봇 (EduPing/NoriArm) 은 기존 WS JPEG 그대로.
        if self.NAME == "gogoping":
            self.camera = WebRTCStreamView()
        elif stream_client is not None:
            self.camera = CameraStreamView(
                robot=self.NAME, stream_client=stream_client, stream_id=0,
            )
        else:
            self.camera = CameraView()
        self.camera_card.body.addWidget(self.camera, 1)
        # ODOM/MAP minHeight 줄여 확보한 세로 폭을 카메라로 양보.
        self.camera_card.setMinimumHeight(420)

        teleop_row_widget = QWidget()
        teleop_row = QHBoxLayout(teleop_row_widget)
        teleop_row.setContentsMargins(0, 0, 0, 0)
        teleop_row.setSpacing(12)
        teleop_row.addWidget(self.teleop_card, 1)
        teleop_row.addWidget(self.camera_pan_card, 1)
        # TeleopCard 와 CameraPanCard 내부가 세로 stack (D-pad 위, cockpit/readout 아래)
        # 이라 합산 height ≈ D-pad(168) + spacing + cockpit(~180) + card padding ≈ 420.
        teleop_row_widget.setMinimumHeight(440)

        self.odom_compact = OdomCompact()
        self.odom_card = Card("ODOM")
        self.odom_card.body.addWidget(self.odom_compact, 1)
        # 180 → 130 — 줄여서 카메라 세로폭에 양보.
        self.odom_card.setMinimumHeight(130)

        from widgets.map_status_card import MapStatusCard
        self.map_status = MapStatusCard()
        self.map_status_card = Card("MAP")
        self.map_status_card.body.addWidget(self.map_status, 1)
        self.map_status_card.setMinimumHeight(130)

        odom_map_widget = QWidget()
        odom_map_row = QHBoxLayout(odom_map_widget)
        odom_map_row.setContentsMargins(0, 0, 0, 0)
        odom_map_row.setSpacing(12)
        odom_map_row.addWidget(self.odom_card, 1)
        odom_map_row.addWidget(self.map_status_card, 1)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(14)
        # ODOM/MAP stretch 도 줄여 카메라로 양보 — camera 10→12, odom_map 3→2.
        # 좌측 합 13 → 18, 카메라 fraction 46% → 67%.
        left_col.addWidget(self.camera_card, 12)
        left_col.addWidget(teleop_row_widget, 4)
        left_col.addWidget(odom_map_widget, 2)

        # 우측 컬럼
        self.map_card = WaypointMapCard(control_url=control_url)
        # 자녀 minimum width (400) 를 풀어줌 — 좌우 1:1 강제 시 영향 없게.
        # 높이 minimum 은 유지 (320).
        self.map_card.setMinimumWidth(0)
        self.lidar_view = LidarScanView()
        self.lidar_card = Card("LiDAR · 실시간 스캔")
        self.lidar_card.body.addWidget(self.lidar_view, 1)
        # polar 가 잘리지 않을 충분한 height 확보 — stat box(50*2) + spacing(16) +
        # header(30) + outer margin(20) + card padding(30) + polar 정사각형 영역
        # (~280) = 470 정도가 안전.
        self.lidar_card.setMinimumHeight(480)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(14)
        right_col.addWidget(self.map_card, 10)
        right_col.addWidget(self.lidar_card, 8)

        # 좌우 컨테이너 QWidget — sizePolicy horizontal=Ignored 로 자녀 sizeHint 무시,
        # main_row 의 stretch 1:1 이 그대로 적용되어 카메라/맵 가로폭 동일하게 보장.
        left_container = QWidget()
        left_container.setLayout(left_col)
        left_container.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        left_container.setMinimumWidth(0)

        right_container = QWidget()
        right_container.setLayout(right_col)
        right_container.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        right_container.setMinimumWidth(0)

        main_row = QHBoxLayout()
        main_row.setContentsMargins(0, 0, 0, 0)
        main_row.setSpacing(14)
        main_row.addWidget(left_container, 1)
        main_row.addWidget(right_container, 1)

        outer.addLayout(main_row, 1)

        # WS state 라우팅 — Dashboard 가 단일 수신점
        self.teleop_client.connect_state_ws(self.on_state)
        self.camera_pan_client.connect_state_ws(self.camera_pan_card.on_state)

        self._tick = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(60)

    def update_battery(self, level: float) -> None:
        """배터리 표시는 TopBar 로 이동 — main.py 의 state_client 콜백이 topbar.update_battery
        를 직접 호출. dashboard 쪽은 no-op (호환성 위해 메서드만 남김)."""
        return

    def update_map_status(self, in_map: bool | None) -> None:
        """``/gogoping/state`` snapshot 의 in_map 을 받아 MAP 카드 갱신.

        True = 🟢 IN MAP, False = 🔴 OUT OF MAP, None = ⚪ UNKNOWN (맵/odom 미수신).
        """
        self.map_status.set_status(in_map)

    def update_pose(self, pose: dict | None) -> None:
        """``/gogoping/state`` snapshot 의 robot_pose 를 받아 ODOM 카드 + MAP 카드
        + 큰 graph map (WaypointMapCard) 의 로봇 마커 갱신.

        /teleop/state 의 odom 과 ODOM 카드 widget 공유 — 둘 다 갱신. (/teleop/state 는
        30Hz, /gogoping/state 는 1Hz 라 /teleop/state 가 더 자주 갱신하지만 양쪽 호환).
        MAP 카드는 /gogoping/state 만 보고 좌표 (디버그 override 반영) 표시.
        """
        if pose is None:
            self.map_status.set_pose(None)
            return
        try:
            x = float(pose.get("x", 0.0))
            y = float(pose.get("y", 0.0))
            yaw = float(pose.get("yaw", 0.0))
            self.odom_compact.set_odom(x, y, yaw)
            self.map_status.set_pose(pose)
            self.map_card.update_robot(x, y, yaw)
        except (TypeError, ValueError):
            pass

    def on_state(self, msg: dict) -> None:
        """WS /teleop/state 단일 수신점. LiDAR/ODOM/Teleop 에 분배."""
        scan = msg.get("scan") or {}
        ranges = scan.get("ranges")
        if ranges is not None:
            hz = float(scan.get("hz", 0.0))
            age_ms = int(scan.get("age_ms", 0))
            self.lidar_view.set_scan(
                float(scan.get("angle_min", 0.0)),
                float(scan.get("angle_inc", 0.0)),
                list(ranges),
            )
            self.lidar_view.set_meta(hz, age_ms)

        odom = msg.get("odom") or {}
        if odom:
            self.odom_compact.set_odom(
                float(odom.get("x", 0.0)),
                float(odom.get("y", 0.0)),
                float(odom.get("yaw", 0.0)),
            )
            self.lidar_view.set_yaw(float(odom.get("yaw", 0.0)))

        # Teleop 카드의 통신 배지 갱신
        self.teleop_card.on_state(msg)

    def _on_tick(self) -> None:
        self._tick += 1
        # 실 stream 위젯은 frame_received signal 로 자동 업데이트, mock CameraView 만 step 필요
        if isinstance(self.camera, CameraView):
            self.camera.step()


# --------------------------------------------------------------------------
# EduPing — 교실 보조
# --------------------------------------------------------------------------


class EduPingDashboard(QWidget):
    NAME = "eduping"
    JOINTS = [
        Joint("Base",     8.0, -180, 180),
        Joint("Shoulder", 24.0, -120, 120),
        Joint("Elbow",   -41.5, -150, 150),
        Joint("Wrist",    16.2, -180, 180),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        meta = ROBOTS[self.NAME]
        accent = meta["color"]

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        self.header = RobotHeader(self.NAME)
        outer.addWidget(self.header)

        main_lay = QHBoxLayout()
        outer.addLayout(main_lay, 1)

        grid = QGridLayout()
        grid.setSpacing(14)
        main_lay.addLayout(grid, 1)

        # 현재 활동
        activity_card = Card("지금 함께하는 활동")
        activity_card.set_watermark("🎨")
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.addWidget(Icon("music", size=28, color=accent))
        self.activity_title = QLabel("음악 시간 보조")
        self.activity_title.setObjectName("hero")
        title_row.addWidget(self.activity_title)
        title_row.addStretch(1)
        self.activity_sub = QLabel("아이들이 부르는 노래에 맞춰 탬버린을 흔드는 중")
        self.activity_sub.setObjectName("heroSub")
        self.activity_sub.setWordWrap(True)
        self.activity_progress = QProgressBar()
        self.activity_progress.setValue(63)
        self.activity_progress.setFormat("수업 진행 %p%")
        self.activity_progress.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {accent}; }}"
        )
        activity_card.body.addLayout(title_row)
        activity_card.body.addWidget(self.activity_sub)
        activity_card.body.addWidget(self.activity_progress)

        # 위치
        location_card = Card("교실 위치")
        location_card.set_watermark("🏫")
        location_card.body.addWidget(self._make_pill("pin", "1반 교실 · 창가 자리",
                                                     accent))
        self.teacher_row = MetricRow("담당 선생님", "김지영 선생님")
        self.kids_row = MetricRow("함께한 친구", "12명")
        self.session_row = MetricRow("세션", "오전 활동 #2")
        for w in (self.teacher_row, self.kids_row, self.session_row):
            location_card.body.addWidget(w)

        # 관절
        joint_card = Card("관절 각도")
        self.joints = JointPanel(self.JOINTS, accent)
        joint_card.body.addWidget(self.joints)

        # 상호작용
        interact_card = Card("오늘의 상호작용")
        interact_card.set_watermark("💬")
        big_row = QHBoxLayout()
        big_row.setSpacing(10)
        big_row.addStretch(1)
        big_row.addWidget(Icon("hug", size=32, color=accent))
        big = QLabel("18명")
        big.setObjectName("hero")
        big_row.addWidget(big)
        big_row.addStretch(1)
        sub = QLabel("의 친구들과 놀았어요")
        sub.setObjectName("heroSub")
        sub.setAlignment(Qt.AlignCenter)
        interact_card.body.addLayout(big_row)
        interact_card.body.addWidget(sub)
        self.smile_row = MetricRow("미소 감지", "342회")
        self.song_row = MetricRow("따라 부른 노래", "7곡")
        self.story_row = MetricRow("들려준 이야기", "3편")
        for w in (self.smile_row, self.song_row, self.story_row):
            interact_card.body.addWidget(w)

        # 시스템
        system_card = Card("시스템 상태")
        system_card.body.addWidget(_battery_row(self, init=91))
        self.cpu_row = MetricRow("CPU", "19%")
        self.temp_row = MetricRow("팔 모터 온도", "38 °C")
        self.uptime_row = MetricRow("가동 시간", "5시간 47분")
        self.audio_row = MetricRow("음성 인식", "정상 · 조용함")
        for w in (self.cpu_row, self.temp_row, self.uptime_row, self.audio_row):
            system_card.body.addWidget(w)

        # 일정
        schedule_card = Card("오늘 남은 활동")
        schedule_card.set_watermark("🗓️")
        self.schedule = TaskQueue(accent)
        self.schedule.set_tasks([
            ("music",      "음악 시간 보조 (진행 중)"),
            ("food",       "간식 시간 안내"),
            ("book",       "그림책 읽어주기"),
            ("palette",    "오후 미술 활동"),
            ("wave",       "하원 인사"),
        ])
        schedule_card.body.addWidget(self.schedule)

        grid.addWidget(activity_card,  0, 0, 1, 2)
        grid.addWidget(location_card,  0, 2, 1, 1)
        grid.addWidget(joint_card,     1, 0, 1, 1)
        grid.addWidget(interact_card,  1, 1, 1, 1)
        grid.addWidget(system_card,    1, 2, 1, 1)
        grid.addWidget(schedule_card,  2, 0, 1, 2)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)

        self._tick = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(100)

    def _make_pill(self, kind: str, text: str, color: str) -> QWidget:
        soft = soften(color, 0.30)
        pill = QWidget()
        pill.setStyleSheet(
            f"background: {soft}; border-radius: 14px;"
        )
        lay = QHBoxLayout(pill)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        lay.addWidget(Icon(kind, size=18, color=color))
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-weight: 700; font-size: 10pt; "
            f"background: transparent;"
        )
        lay.addWidget(lbl)
        lay.addStretch(1)
        return pill

    def _on_tick(self) -> None:
        self._tick += 1
        angles = []
        for i, j in enumerate(self.JOINTS):
            wobble = math.sin(self._tick * 0.18 + i * 1.2) * 12
            angles.append(j.angle + wobble)
        self.joints.update_angles(angles)

        if self._tick % 8 == 0:
            self.cpu_row.set_value(f"{random.randint(15, 26)}%")
        if self._tick % 30 == 0:
            cur = self.activity_progress.value()
            self.activity_progress.setValue(min(100, cur + 1))


# --------------------------------------------------------------------------
# 도우미
# --------------------------------------------------------------------------


def _battery_row(parent_owner, init: int = 82) -> QWidget:
    """배터리 라벨 + 바. parent_owner.battery 에 BatteryBar 저장."""
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lay.addWidget(IconText("battery", "배터리", size=16,
                           color=COLORS["text_muted"],
                           text_color=COLORS["text_muted"], font_pt=12))
    bar = BatteryBar()
    bar.set_pct(init)
    parent_owner.battery = bar
    lay.addWidget(bar)
    return box


def _kv_row(label: str, value_widget: QWidget) -> QWidget:
    """라벨 + 임의 위젯(값) 한 줄."""
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    l = QLabel(label)
    l.setObjectName("metricLabel")
    lay.addWidget(l)
    lay.addStretch(1)
    lay.addWidget(value_widget)
    return box


# --------------------------------------------------------------------------
# EduPing 컨트롤 대시보드 — OpenArm 3D 뷰어 + 관절 범위 슬라이더 (충돌 방지 튜닝)
# --------------------------------------------------------------------------

import json
import math as _math
from pathlib import Path as _Path

from PyQt5.QtCore import pyqtSignal


def _make_selectable(label: QLabel) -> None:
    """QLabel 텍스트를 마우스 드래그 + Ctrl+C 로 복사 가능하게.

    에러 메시지 (PyQtWebEngine 미설치, 서버 timeout 등) 를 복붙해서 issue tracker 에
    붙여 넣을 수 있게 — 기본 QLabel 은 텍스트가 read-only 인데도 선택조차 안 된다.
    """
    label.setTextInteractionFlags(
        Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard,
    )
    label.setCursor(Qt.IBeamCursor)


class _JointHoverFilter(QObject):
    """Mouse-enter / mouse-leave on a joint box → highlight the matching joint in
    the embedded 3D viewer via window.highlightJoint() / window.clearJointHighlight(),
    and toggle a local pulse-dot indicator inside the box (visual confirmation that
    the cursor is registered, even before looking at the 3D viewer).

    Enter / Leave events fire as the cursor crosses each child widget too — but we
    only want to clear the highlight when the cursor truly leaves the BOX, not when
    it just moves between children. The `_entered_widgets` set tracks which children
    are currently entered; we clear only when the set becomes empty.
    """

    def __init__(
        self,
        dashboard: "EduPingControlDashboard",
        joint_name: str,
        *,
        indicator: QLabel | None = None,
    ) -> None:
        super().__init__(dashboard)
        self._dashboard = dashboard
        self._joint_name = joint_name
        self._indicator = indicator
        self._entered: set[int] = set()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        et = event.type()
        if et == QEvent.Enter:
            was_empty = not self._entered
            self._entered.add(id(obj))
            if was_empty:
                self._dashboard._highlight_joint_in_viewer(self._joint_name)
                if self._indicator is not None:
                    self._indicator.setVisible(True)
        elif et == QEvent.Leave:
            self._entered.discard(id(obj))
            if not self._entered:
                self._dashboard._clear_joint_highlight_in_viewer()
                if self._indicator is not None:
                    self._indicator.setVisible(False)
        return False  # don't consume — let the widget see its events normally


# OpenArm v10 (듀얼 암) — left/right 각 7 arm joints + 1 finger = 16 joints.
# 실제 joint name·URDF 한계는 control_service.eduping.joint_limits.DEFAULT_JOINT_SPECS
# 에서 import — 백엔드와 동일 source of truth 유지.
# Control Server 미실행/PYTHONPATH 미설정 환경에서도 admin-app 이 뜨도록 lazy + fallback.

def _openarm_joint_specs() -> list[tuple[str, str, float, float, str]]:
    """(joint_name, label, urdf_lower, urdf_upper, unit) 16개. fallback 시 빈 리스트."""
    try:
        import sys as _sys
        from pathlib import Path as _P
        _repo_root = _P(__file__).resolve().parents[2]
        _cs = _repo_root / "service" / "control-service"
        _db = _repo_root / "db" / "control-db"
        for _path in (_cs, _db):
            _spath = str(_path)
            if _spath not in _sys.path:
                _sys.path.insert(0, _spath)
        from control_service.eduping.joint_limits import DEFAULT_JOINT_SPECS  # type: ignore
        return list(DEFAULT_JOINT_SPECS)
    except Exception:
        # 백엔드 import 못 하면 빈 리스트 — UI 가 안내 메시지만 띄움.
        return []


_OPENARM_SPECS = _openarm_joint_specs()


def _openarm_default_limits() -> dict[str, dict[str, float]]:
    """초기 슬라이더 값 — URDF (lower, upper) 그대로. 사용자가 좁혀서 충돌 방지."""
    return {
        name: {"min": lo, "max": hi}
        for name, _label, lo, hi, _unit in _OPENARM_SPECS
    }


class EduPingControlDashboard(QWidget):
    """EduPing OpenArm 관리자 대시보드.

    좌측: QWebEngineView 로 robot-web 의 OpenArm 뷰어 임베드 (실시간 3D pose).
    우측: 각 관절의 Min/Max 한계 슬라이더(double spin box pair) + 저장/복원 버튼.

    저장 버튼은 Control Server 의 `/api/eduping/joint-limits` (POST) 로 전송.
    Control Server 는 이 한계를 dance replay 시 frame 별로 적용 (clip) 해 학습
    데이터가 한계를 벗어나는 경우 강제 잘라 충돌을 막는다.
    """

    limits_save_requested = pyqtSignal(dict)  # {joint_name: {"min": float, "max": float}}
    limits_reset_requested = pyqtSignal()
    # rclpy 스핀 스레드 → GUI 스레드 마샬링. Qt 가 cross-thread signal 을 queue 한다.
    _joint_state_received = pyqtSignal(dict)
    # 실물 재생 (안전) — main.py 가 control-service 로 limits POST + play POST.
    safe_play_requested = pyqtSignal(dict)  # {kind, slug, limits}

    # Viewer URL — points at robot-web with `?embed=openarm`, which short-circuits
    # App.vue to render the same OpenarmViewer (three.js + urdf-loader) the Mugunghwa
    # game uses, in fullscreen. The embed page exposes `window.highlightJoint(name)`
    # and `window.clearJointHighlight()` globals so this PyQt side can spotlight a
    # link on cursor hover.
    #
    # HTTPS by default — Vite dev server uses mkcert and serves https on 5173. The
    # admin viewer below installs `_DevPermissivePage` so the self-signed cert
    # doesn't block loading. If the user runs `VITE_HTTPS=false npm run dev`,
    # override with `ADMIN_OPENARM_VIEWER_URL=http://localhost:5173/?embed=openarm`.
    DEFAULT_VIEWER_URL = "https://localhost:5173/?embed=openarm"

    def __init__(self, parent=None):
        super().__init__(parent)
        meta = ROBOTS["eduping"]
        accent = meta["color"]
        self._joint_widgets: dict[str, tuple[QDoubleSpinBox, QDoubleSpinBox]] = {}
        # Live "현재" QLabel per joint — updated from the rclpy joint-state pump.
        self._joint_current_labels: dict[str, QLabel] = {}
        # Hover filters per joint — kept alive (else GC kills them).
        self._hover_filters: list[_JointHoverFilter] = []
        # Debounced limit push to the embedded viewer (so slider changes
        # immediately clip the displayed leader pose — visual self-collision
        # prevention without needing to click 저장).
        self._limits_push_timer = QTimer(self)
        self._limits_push_timer.setSingleShot(True)
        self._limits_push_timer.setInterval(150)
        self._limits_push_timer.timeout.connect(self._push_limits_to_viewer)
        # Latest snapshot from rclpy; consumed by the 10Hz label-update timer
        # below. Decouples 50Hz callback rate from UI paint cost.
        self._latest_snap: dict | None = None
        self._label_update_timer = QTimer(self)
        self._label_update_timer.setInterval(100)  # 10 Hz
        self._label_update_timer.timeout.connect(self._tick_label_update)
        self._label_update_timer.start()
        # Standalone rclpy 구독자 — 켜져 있으면 control-service 우회. 시작은 EduPing
        # 탭이 처음 활성화될 때 (main.py 의 _on_tab_changed) 한 번만.
        self._joint_subscriber: Any = None
        self._joint_subscriber_started = False
        # Throttle JS injection — leader publishes at 50Hz; we pump to the embedded
        # three.js scene at 30Hz to match the viewer's 30 FPS render cap. 15Hz
        # was noticeably choppy during routine playback (the renderer ran at
        # 30 FPS but on stale data), so the dance/gesture looked stuttery.
        # 30Hz pump + 30Hz playback emit (see RoutinePlayback rate below) means
        # every emitted frame lines up with a render tick.
        self._js_pump_min_interval_s = 1.0 / 30.0
        self._js_pump_last_mono: float = 0.0
        self._js_pump_pending: dict | None = None
        # Routine playback — replays a recorded dance/greeting through the same
        # joint-state pipeline as the live rclpy subscriber, so all limit
        # clipping applies. Used to verify safe-range settings without running
        # the real arm.
        self._playback: Any = None
        # When True, live rclpy leader frames are dropped — the viewer animates
        # the playback only. Flipped True on play, False on stop / end-of-routine.
        # Without this gate the viewer flickers between leader pose and the
        # playback pose at the combined ~100Hz update rate.
        self._playback_active: bool = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        self.header = RobotHeader("eduping")
        outer.addWidget(self.header)

        # 본문 — 좌(뷰어) / 우(슬라이더) 가로 분할.
        body = QHBoxLayout()
        body.setSpacing(14)
        outer.addLayout(body, 1)

        # ── 좌: 3D 뷰어 ─────────────────────────────────────────────
        viewer_card = Card("OpenArm 3D 뷰어")
        viewer_card.set_watermark("🦾")

        # 팔 동기화 (teleop) UI 제거 — 율동 녹화 흐름처럼 follower 연결 시 control-service
        # 의 eduping bridge 가 leader publish 를 자동으로 forward. 별도 토글 불필요.

        viewer_url = os.environ.get(
            "ADMIN_OPENARM_VIEWER_URL", self.DEFAULT_VIEWER_URL,
        )
        if _HAS_WEBENGINE and QWebEngineView is not None:
            self.viewer = QWebEngineView()
            self.viewer.setMinimumSize(520, 420)
            # Install permissive page so localhost mkcert self-signed certs don't
            # block load. Stored on self so it isn't GC'd.
            if _DevPermissivePage is not None:
                self._viewer_page = _DevPermissivePage(self.viewer)
                self.viewer.setPage(self._viewer_page)
            _tune_webengine_view(self.viewer)
            self._viewer_embed_url = viewer_url
            self._compare_prepare_thread = None
            self._viewer_compare_mode = False
            self._pending_compare_payload_json: str | None = None
            self.viewer.setUrl(QUrl(viewer_url))
            try:
                self.viewer.loadFinished.connect(self._on_viewer_load_finished)
            except Exception:
                pass
            viewer_card.body.addWidget(self.viewer, 1)

            # Diagnostic line — rclpy subscription state + topic + msg count + age.
            # Updates every 500ms so the user can see if the topic is alive.
            self._ros_diag_label = QLabel("rclpy: 미시작")
            self._ros_diag_label.setStyleSheet(
                f"color: {COLORS['text_muted']}; font-size: 9pt; "
                f"background: transparent;"
            )
            _make_selectable(self._ros_diag_label)
            viewer_card.body.addWidget(self._ros_diag_label)
            self._viewer_url_label = QLabel(viewer_url)
            self._viewer_url_label.setWordWrap(True)
            self._viewer_url_label.setStyleSheet(
                f"color: {COLORS['text_muted']}; font-size: 8pt; "
                f"background: transparent;"
            )
            _make_selectable(self._viewer_url_label)
            viewer_card.body.addWidget(self._viewer_url_label)
            self._ros_diag_timer = QTimer(self)
            self._ros_diag_timer.timeout.connect(self._refresh_ros_diag)
            self._ros_diag_timer.start(500)
        else:
            placeholder = QLabel(
                "PyQtWebEngine 미설치 — 3D 뷰어를 표시하려면:\n"
                "    pip install PyQtWebEngine\n"
                f"이후 ADMIN_OPENARM_VIEWER_URL 환경변수로 뷰어 URL 지정\n"
                f"(기본 {viewer_url})"
            )
            placeholder.setWordWrap(True)
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet(
                f"color: {COLORS['text_muted']}; font-size: 11pt; padding: 24px; "
                f"background: {COLORS['panel']}; border-radius: 12px;"
            )
            placeholder.setMinimumSize(520, 420)
            # 에러 메시지 복사 가능하게 — 드래그 선택 + Ctrl+C.
            _make_selectable(placeholder)
            viewer_card.body.addWidget(placeholder, 1)
            self.viewer = None
            self._viewer_embed_url = viewer_url
            self._viewer_compare_mode = False
        body.addWidget(viewer_card, 2)

        # ── 우: 녹화 재생 + 관절 범위 슬라이더 (좌/우 듀얼 암) ─────────────────
        sliders_card = Card("OpenArm 관절 범위 — 좌/우 듀얼 암")
        sliders_card.set_watermark("📐")
        # 녹화 재생 — 율동/인사 .yaml 을 viewer 에 시뮬레이션. 실제 arm 동작 X.
        # 관절 한계 슬라이더가 클립되는지 시각 확인용. 위에 가로 row 로 배치.
        self._build_playback_row(sliders_card.body)
        help_lbl = QLabel(
            "녹화된 dance/replay 가 관절 한계를 넘으면 Control Server 가 자동으로\n"
            "잘라(clip) 모터·스틸 베이스 충돌을 막습니다. 각 스핀박스 range 는\n"
            "URDF 한계(절대 한계) — 그 안에서 더 좁히면 안전 윈도우가 줄어듭니다.\n"
            "단위는 arm joint = rad, finger = m (prismatic)."
        )
        help_lbl.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 9pt; "
            f"background: transparent;"
        )
        help_lbl.setWordWrap(True)
        _make_selectable(help_lbl)
        sliders_card.body.addWidget(help_lbl)

        if not _OPENARM_SPECS:
            warn = QLabel(
                "joint_limits 스펙을 import 할 수 없습니다 — Control Server 패키지가\n"
                "PYTHONPATH 에 있는지 확인하세요.\n"
                "(service/control-service, db/control-db 가 보이지 않는 환경)"
            )
            warn.setWordWrap(True)
            _make_selectable(warn)
            warn.setStyleSheet(
                f"color: #c14545; font-size: 10pt; padding: 16px; "
                f"background: {COLORS['panel']}; border-radius: 8px;"
            )
            sliders_card.body.addWidget(warn)
        else:
            # 좌/우 두 컬럼. 각 컬럼에 7 arm joint + 1 finger = 8 슬라이더.
            cols = QHBoxLayout()
            cols.setSpacing(20)
            left_form = self._build_arm_form("왼팔", "openarm_left_")
            right_form = self._build_arm_form("오른팔", "openarm_right_")
            cols.addLayout(left_form, 1)
            cols.addLayout(right_form, 1)
            # 16 슬라이더라 세로로 길어질 수 있어 스크롤 wrap.
            cols_host = QWidget()
            cols_host.setLayout(cols)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.NoFrame)
            scroll.setWidget(cols_host)
            sliders_card.body.addWidget(scroll, 1)

        # 버튼 — 저장 / URDF 기본값 복원.
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.reset_btn = QPushButton("URDF 기본값")
        self.save_btn = QPushButton("저장")
        self.save_btn.setStyleSheet(
            f"QPushButton {{ background: {accent}; color: white; "
            f"padding: 8px 18px; border-radius: 8px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {soften(accent, 0.15)}; }}"
        )
        self.reset_btn.clicked.connect(self._on_reset_clicked)
        self.save_btn.clicked.connect(self._on_save_clicked)
        btn_row.addStretch(1)
        btn_row.addWidget(self.reset_btn)
        btn_row.addWidget(self.save_btn)
        sliders_card.body.addLayout(btn_row)

        # 마지막 저장 결과 — 성공/실패 메시지 짧게.
        self.save_status = QLabel("")
        self.save_status.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 9pt; "
            f"background: transparent;"
        )
        self.save_status.setWordWrap(True)
        # 서버 timeout 같은 에러 메시지를 그대로 복사 가능하게.
        _make_selectable(self.save_status)
        sliders_card.body.addWidget(self.save_status)

        body.addWidget(sliders_card, 3)

    # ------------------------------------------------- 슬라이더 폼 빌더
    def _build_arm_form(self, title: str, name_prefix: str) -> QVBoxLayout:
        """한쪽 팔 (왼/오) 의 spec 만 골라 (Min spin / Max spin) 행을 만든다.

        반환은 QVBoxLayout — 호출자가 좌/우 두 컬럼을 QHBoxLayout 에 넣는다.
        spin box range 는 각 joint 의 URDF lower/upper 그대로 — 그 안에서만 슬라이딩.
        """
        column = QVBoxLayout()
        column.setSpacing(6)
        column.setContentsMargins(0, 0, 0, 0)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 13pt; font-weight: 700; "
            f"background: transparent;"
        )
        column.addWidget(title_lbl)

        defaults = _openarm_default_limits()
        for name, label, urdf_lo, urdf_hi, unit in _OPENARM_SPECS:
            if not name.startswith(name_prefix):
                continue
            row = QHBoxLayout()
            row.setSpacing(6)
            # 단위에 맞게 스텝 다르게 — rad 는 0.05, m (finger) 는 0.001.
            step = 0.05 if unit == "rad" else 0.001
            decimals = 3 if unit == "rad" else 4
            suffix = f" {unit}"

            min_box = QDoubleSpinBox()
            min_box.setRange(urdf_lo, urdf_hi)
            min_box.setDecimals(decimals)
            min_box.setSingleStep(step)
            min_box.setSuffix(suffix)
            min_box.setValue(defaults[name]["min"])
            min_box.setObjectName(f"{name}_min")

            max_box = QDoubleSpinBox()
            max_box.setRange(urdf_lo, urdf_hi)
            max_box.setDecimals(decimals)
            max_box.setSingleStep(step)
            max_box.setSuffix(suffix)
            max_box.setValue(defaults[name]["max"])
            max_box.setObjectName(f"{name}_max")

            # Min 이 Max 를 추월하지 못하게 cross-link.
            min_box.valueChanged.connect(
                lambda v, mb=max_box: mb.setMinimum(v),
            )
            max_box.valueChanged.connect(
                lambda v, mb=min_box: mb.setMaximum(v),
            )
            # Any slider change → debounced push to the embedded viewer so the
            # displayed arm immediately clips to the new safe range (visual
            # self-collision prevention; doesn't require pressing 저장).
            min_box.valueChanged.connect(lambda _v: self._limits_push_timer.start())
            max_box.valueChanged.connect(lambda _v: self._limits_push_timer.start())

            label_lbl = QLabel(label)
            label_lbl.setStyleSheet(
                f"color: {COLORS['text']}; font-size: 10pt; font-weight: 600; "
                f"background: transparent; border: none;"
            )
            # 현재 값 — leader bringup 의 joint state 가 들어오면 _update_current_joint_labels
            # 가 매 프레임 (subscriber rate) 갱신. 단위는 unit (arm = rad, finger = m).
            current_lbl = QLabel("—")
            current_lbl.setStyleSheet(
                f"color: #c14545; font-size: 10pt; font-weight: 800; "
                f"font-variant-numeric: tabular-nums; "
                f"background: transparent; border: none; min-width: 80px;"
            )
            current_lbl.setAlignment(Qt.AlignCenter)
            self._joint_current_labels[name] = current_lbl
            min_caption = QLabel("Min:")
            min_caption.setStyleSheet("background: transparent; border: none;")
            max_caption = QLabel("Max:")
            max_caption.setStyleSheet("background: transparent; border: none;")
            row.addWidget(label_lbl, 2)
            row.addWidget(current_lbl, 1)
            row.addWidget(min_caption)
            row.addWidget(min_box, 1)
            row.addWidget(max_caption)
            row.addWidget(max_box, 1)

            # Visible "joint box" — rounded card with clear hover state. The pulse
            # dot on the right turns visible when hovered, mirroring the 3D
            # highlight so the user sees which joint they're hovering even before
            # looking at the viewer.
            dot = QLabel("●")
            dot.setStyleSheet(
                "color: #ff4d6d; font-size: 14pt; font-weight: 900; "
                "background: transparent; border: none; padding: 0 4px;"
            )
            dot.setVisible(False)
            row.addWidget(dot)

            box = QFrame()
            box.setObjectName("jointBox")
            box.setLayout(row)
            box.setAttribute(Qt.WA_Hover, True)
            box.setStyleSheet(
                "QFrame#jointBox {"
                f"  background: {COLORS['panel']};"
                f"  border: 1px solid {COLORS['border']};"
                "  border-radius: 10px;"
                "  padding: 6px 10px;"
                "  margin: 2px 0;"
                "}"
                "QFrame#jointBox:hover {"
                f"  background: {soften('#ff4d6d', 0.85)};"
                "  border-color: #ff4d6d;"
                "}"
            )

            # Hover anywhere on this box → spotlight the matching 3D link, and show
            # the pulse dot inside this box. Filter installed on every child too so
            # Enter/Leave fire even when the cursor passes over a child widget.
            hover = _JointHoverFilter(self, name, indicator=dot)
            self._hover_filters.append(hover)
            for w in (box, label_lbl, min_box, max_box, min_caption, max_caption):
                w.installEventFilter(hover)

            column.addWidget(box)
            self._joint_widgets[name] = (min_box, max_box)

        column.addStretch(1)
        return column

    def _refresh_ros_diag(self) -> None:
        """Update the rclpy diag line — shows topic, msg count, and last-msg age.

        Run by a 500ms QTimer on the GUI thread. Reads counters published by the
        subscriber (set on the rclpy spin thread); int reads are atomic in CPython
        so no extra lock needed.
        """
        label = getattr(self, "_ros_diag_label", None)
        if label is None:
            return
        sub = self._joint_subscriber
        if sub is None:
            if not self._joint_subscriber_started:
                label.setText("rclpy: 미시작 (EduPing 탭 활성화 시 시작)")
                return
            # Subscriber start was attempted but failed — surface the exact reason
            # so the user can act (most common: rclpy not in this Python env, or
            # ROS env not sourced before launch).
            from services.eduping_joint_subscriber import last_import_error
            err = last_import_error() or "원인 불명"
            label.setText(
                "rclpy: 시작 실패 — " + err + "  "
                "(터미널에서 `source /opt/ros/jazzy/setup.bash` 후 admin-app 재실행)"
            )
            return
        try:
            n = sub.msg_count
            topic = sub.topic
            last_mono = sub.last_msg_mono
            sub_err = sub.last_error
        except AttributeError:
            label.setText("rclpy: 상태 조회 실패")
            return
        if sub_err is not None:
            label.setText(f"rclpy: {sub_err}")
            return
        if n == 0:
            label.setText(
                f"rclpy: 대기 중 — topic={topic} (0 msgs). "
                "leader bringup 실행 + ROS_DOMAIN_ID 일치 확인."
            )
            return
        import time as _time
        age = _time.monotonic() - last_mono if last_mono > 0 else float("inf")
        label.setText(
            f"rclpy: live — topic={topic} ({n} msgs, last {age:.1f}s ago)"
        )

    # ------------------------------------------------- routine playback (preview)
    def _build_playback_row(self, parent_box: QVBoxLayout) -> None:
        """녹화된 routine (dance/greeting) 목록 + 재생 / 정지 컨트롤.

        재생 시 background thread 가 routine 의 keyframe 을 시각 sample_hz 으로
        interp → 매 frame 을 self._joint_state_received signal 로 emit → 평소
        leader 메시지처럼 viewer + 한계 clipping 파이프라인을 거친다.
        """
        try:
            from services.routine_playback import (
                RoutinePlayback, list_routines,
            )
        except Exception as e:  # noqa: BLE001
            err = QLabel(
                f"녹화 재생 모듈 로드 실패: {e!r}"
            )
            err.setStyleSheet(
                f"color: #c14545; font-size: 9pt; background: transparent;"
            )
            _make_selectable(err)
            parent_box.addWidget(err)
            return

        self._routine_items: list[dict[str, str]] = list_routines()
        row = QHBoxLayout()
        row.setSpacing(8)
        title = QLabel("녹화 미리보기")
        title.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 10pt; font-weight: 700; "
            f"background: transparent;"
        )
        row.addWidget(title)

        self._routine_combo = QComboBox()
        if not self._routine_items:
            self._routine_combo.addItem("(녹화 파일 없음)")
            self._routine_combo.setEnabled(False)
        else:
            for it in self._routine_items:
                self._routine_combo.addItem(
                    f"[{it['kind']}] {it['display_name']}", it["path"],
                )
        row.addWidget(self._routine_combo, 2)

        self._play_btn = QPushButton("▶ 미리보기")
        self._stop_btn = QPushButton("■ 정지")
        self._stop_btn.setEnabled(False)
        self._play_btn.setStyleSheet(
            "QPushButton { background: #16a34a; color: white;"
            "  padding: 6px 14px; border-radius: 6px; font-weight: 700; }"
            "QPushButton:hover { background: #15803d; }"
            "QPushButton:disabled { background: #cbd5e1; color: #6b7280; }"
        )
        self._stop_btn.setStyleSheet(
            "QPushButton { background: #c14545; color: white;"
            "  padding: 6px 14px; border-radius: 6px; font-weight: 700; }"
            "QPushButton:hover { background: #a83b3b; }"
            "QPushButton:disabled { background: #cbd5e1; color: #6b7280; }"
        )
        self._play_btn.clicked.connect(self._on_play_routine)
        self._stop_btn.clicked.connect(self._on_stop_routine)
        row.addWidget(self._play_btn)
        row.addWidget(self._stop_btn)

        # 실물 재생 (안전) — control-service 를 거쳐 follower 로 trajectory 송신.
        # dance_stream 이 매 frame 마다 현재 slider 한계로 clip → 실 motor 가
        # 그 안에서만 움직임. Control Server 필요.
        self._safe_play_btn = QPushButton("🔒 실물 재생 (안전)")
        self._safe_play_btn.setStyleSheet(
            "QPushButton { background: #2563eb; color: white;"
            "  padding: 6px 14px; border-radius: 6px; font-weight: 700; }"
            "QPushButton:hover { background: #1d4ed8; }"
            "QPushButton:disabled { background: #cbd5e1; color: #6b7280; }"
        )
        self._safe_play_btn.clicked.connect(self._on_safe_play)
        row.addWidget(self._safe_play_btn)

        # 🎬 녹화 기반 안전 자동 탐색 — 현재 선택된 routine 의 모든 keyframe pose 를
        # viewer 에서 차례로 적용 → AABB 충돌 검사 → "충돌하지 않는 frame" 들에서만
        # 각 joint 의 observed min/max 를 기록 → 그것이 slider 한계가 된다.
        # 즉, 이 dance 가 자연스럽게 흐를 수 있는 가장 좁은 안전 윈도우. 충돌
        # frame 은 자동으로 잘려 (clipping) 실 motor 는 그 좁은 윈도우 안에서만
        # 재생됨. 녹화가 dropdown 에 선택돼 있어야 동작.
        self._auto_safe_btn = QPushButton("🎬 녹화 기반 안전 자동 탐색")
        self._auto_safe_btn.setStyleSheet(
            "QPushButton { background: #f59e0b; color: white;"
            "  padding: 6px 14px; border-radius: 6px; font-weight: 700; }"
            "QPushButton:hover { background: #d97706; }"
            "QPushButton:disabled { background: #cbd5e1; color: #6b7280; }"
        )
        self._auto_safe_btn.clicked.connect(self._on_auto_find_safe_limits)
        row.addWidget(self._auto_safe_btn)

        # 안전본 저장 — 원본은 그대로 두고 slider 한계로 clip 한 새 routine 파일을
        # `<slug>-safe/` 디렉토리에 작성. 차후 율동/인사 목록에서 별도 항목으로 보임.
        self._safe_save_btn = QPushButton("💾 안전본 저장")
        self._safe_save_btn.setStyleSheet(
            "QPushButton { background: " + COLORS["panel"] + ";"
            f"  color: {COLORS['text']};"
            f"  border: 1.5px solid {COLORS['border']};"
            "  padding: 6px 14px; border-radius: 6px; font-weight: 700; }"
            "QPushButton:hover { border-color: #2563eb; color: #2563eb; }"
            "QPushButton:disabled { color: #6b7280; }"
        )
        self._safe_save_btn.clicked.connect(self._on_save_safe_version)
        row.addWidget(self._safe_save_btn)

        # ↔ 비교 — 분석 직전 한계와 분석 결과 사이를 toggle. 각 모드에서 ▶ 미리보기
        # 를 눌러 시뮬레이션을 다시 보면 viewer 가 그 한계로 clip 하므로 자기충돌
        # 발생 여부를 시각적으로 비교할 수 있다. 분석을 한 번도 안 했으면 비활성.
        self._compare_btn = QPushButton("↔ 분석 전과 비교")
        self._compare_btn.setEnabled(False)
        self._compare_btn.setToolTip(
            "녹화 기반 안전 분석 직전 한계로 되돌립니다. 다시 누르면 분석 결과 재적용."
        )
        self._compare_btn.setStyleSheet(
            "QPushButton { background: #ede9fe; color: #5b21b6;"
            "  border: 1.5px solid #8b5cf6;"
            "  padding: 6px 14px; border-radius: 6px; font-weight: 700; }"
            "QPushButton:hover { background: #ddd6fe; }"
            "QPushButton:disabled { background: #f1f5f9; color: #94a3b8;"
            "  border-color: #cbd5e1; }"
        )
        self._compare_btn.clicked.connect(self._on_toggle_limits_snapshot)
        row.addWidget(self._compare_btn)

        # 🖼 좌측 QWebEngineView(웹 브라우저) 에서 분석 전/후 비교 페이지 로드.
        self._compare_window_btn = QPushButton("🖼 웹뷰어에서 비교 재생")
        self._compare_window_btn.setEnabled(False)
        self._compare_window_btn.setToolTip(
            "좌측 OpenArm 웹뷰어(QWebEngine)에 비교 페이지를 띄웁니다. "
            "분석 전/후 한계를 좌우로 동시 재생하고, 한쪽을 돌리면 다른 쪽도 따라갑니다."
        )
        self._compare_window_btn.setStyleSheet(
            "QPushButton { background: #5b21b6; color: white;"
            "  padding: 6px 14px; border-radius: 6px; font-weight: 700; }"
            "QPushButton:hover { background: #4c1d95; }"
            "QPushButton:disabled { background: #cbd5e1; color: #6b7280; }"
        )
        self._compare_window_btn.clicked.connect(self._on_open_compare_in_viewer)
        row.addWidget(self._compare_window_btn)

        self._exit_compare_btn = QPushButton("↩ 실시간 뷰어")
        self._exit_compare_btn.setEnabled(False)
        self._exit_compare_btn.setToolTip(
            "비교 페이지를 닫고 실시간 leader OpenArm 뷰어로 돌아갑니다."
        )
        self._exit_compare_btn.setStyleSheet(
            "QPushButton { background: #334155; color: white;"
            "  padding: 6px 14px; border-radius: 6px; font-weight: 700; }"
            "QPushButton:hover { background: #1e293b; }"
            "QPushButton:disabled { background: #e2e8f0; color: #94a3b8; }"
        )
        self._exit_compare_btn.clicked.connect(self._on_exit_compare_viewer)
        row.addWidget(self._exit_compare_btn)

        # Internal snapshots used by _on_toggle_limits_snapshot. None until a
        # scan completes.
        self._limits_before_scan: dict[str, dict[str, float]] | None = None
        self._limits_after_scan: dict[str, dict[str, float]] | None = None
        self._showing_scan_result: bool = False

        # Status label — own row underneath the buttons, full width + wordWrap
        # so long messages (e.g. "녹화 기반 안전 자동 탐색 완료: 16 joints 분석
        # … 마음에 들면 [저장] 눌러서 control-service 에 영구화하세요.") aren't
        # truncated to a fixed column.
        self._playback_status = QLabel("정지")
        self._playback_status.setWordWrap(True)
        self._playback_status.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 9pt; "
            f"background: transparent;"
        )
        _make_selectable(self._playback_status)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        outer.addLayout(row)
        outer.addWidget(self._playback_status)

        wrapper = QWidget()
        wrapper.setLayout(outer)
        wrapper.setStyleSheet(
            f"background: {COLORS['bg']}; border-radius: 8px; padding: 6px 8px;"
        )
        parent_box.addWidget(wrapper)

        # Build the playback instance once — its on_frame callback feeds back
        # into the same signal the rclpy subscriber uses, so the rest of the
        # viewer/limit pipeline is unchanged. End-of-routine detection happens
        # via _refresh_playback_progress (200ms poll) — no on_finished needed.
        # 30Hz playback emit — paired with the 30Hz JS pump throttle so each
        # emitted frame reaches the viewer (no wasted Qt signal queue traffic).
        # Was 50Hz which queued and got down-sampled, contributing to playback
        # lag in the WebEngine.
        self._playback = RoutinePlayback(
            on_frame=lambda snap: self._joint_state_received.emit(snap),
            rate_hz=30.0,
        )
        # Progress poll timer.
        self._playback_progress_timer = QTimer(self)
        self._playback_progress_timer.setInterval(200)
        self._playback_progress_timer.timeout.connect(self._refresh_playback_progress)
        self._playback_progress_timer.start()

    def _on_play_routine(self) -> None:
        if self._playback is None:
            return
        path = self._routine_combo.currentData()
        if not isinstance(path, str):
            return
        ok = self._playback.start(path)
        if not ok:
            self._playback_status.setText(
                self._playback.last_error or "재생 실패",
            )
            return
        # Silence live leader frames while playback runs — otherwise the viewer
        # flickers between leader pose and the playback pose at ~100Hz combined.
        self._playback_active = True
        self._play_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._playback_status.setText("재생 중… (leader 정지)")

    def _on_stop_routine(self) -> None:
        if self._playback is None:
            return
        self._playback.stop()
        self._playback_active = False
        self._play_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._playback_status.setText("정지 (leader 다시 활성)")

    def _on_auto_find_safe_limits(self) -> None:
        """녹화 dropdown 에서 고른 routine 의 keyframe pose 들을 viewer 에 차례로
        적용 → AABB 충돌 검사 → 충돌 안 한 frame 들의 per-joint observed min/max
        를 그대로 slider 한계로 채운다.

        - 다중 joint 가 "실제로 동시에" 움직이는 그 dance 의 상황을 그대로 분석함.
          (단일 joint sweep 보다 정확.)
        - 충돌 frame 은 무시 → 그 frame 들의 angle 은 한계 밖이 됨 → 실 motor 재생
          시 자동으로 clip 되어 자기충돌 회피.
        - leader feed 는 scan 동안 silence (viewer 가 leader pose 로 덮어쓰지
          않도록).
        """
        item = self._selected_routine()
        if item is None:
            self._playback_status.setText(
                "녹화 dropdown 에서 분석할 routine 을 먼저 선택하세요."
            )
            return
        view = getattr(self, "viewer", None)
        if view is None:
            self._playback_status.setText("viewer 미준비 — 자동 탐색 불가")
            return
        page = view.page()
        if page is None:
            self._playback_status.setText("viewer page 미준비")
            return

        try:
            from services.routine_playback import load_recording_for_scan
        except Exception as e:  # noqa: BLE001
            self._playback_status.setText(f"녹화 로더 import 실패: {e!r}")
            return

        recording = load_recording_for_scan(item["path"])
        if recording is None:
            self._playback_status.setText(
                f"녹화 파일을 읽지 못했습니다 — {item.get('display_name', '?')}"
            )
            return
        n_frames = len(recording.get("frames", []))
        if n_frames == 0:
            self._playback_status.setText("녹화에 keyframe 이 없습니다.")
            return

        self._auto_safe_btn.setEnabled(False)
        self._playback_active = True
        self._playback_status.setText(
            f"녹화 기반 안전 분석 중… ({item['display_name']}, {n_frames} frames)"
        )
        # 분석 결과 status 에 routine 이름 출력하기 위해 임시 보관.
        self._last_scan_label = item.get("display_name", "?")
        self._last_scan_n_frames = n_frames
        # 비교 toggle 용 스냅샷 — 분석 직전 슬라이더 상태를 그대로 기억.
        self._limits_before_scan = self.collect_limits()

        import json
        payload = json.dumps(recording)
        page.runJavaScript(
            "window.scanRecordingForSafeOpenarmLimits "
            f"? window.scanRecordingForSafeOpenarmLimits({payload}) : null",
            self._on_auto_safe_limits_result,
        )

    def _on_auto_safe_limits_result(self, result: Any) -> None:
        """JS callback — `result` is `{joint_name: {min, max}}` or null."""
        self._auto_safe_btn.setEnabled(True)
        self._playback_active = False  # resume leader feed
        label = getattr(self, "_last_scan_label", "?")
        n_frames = getattr(self, "_last_scan_n_frames", 0)
        if not isinstance(result, dict) or not result:
            self._playback_status.setText(
                "녹화 기반 안전 분석 실패 — viewer 가 URDF 로딩 중이거나 "
                "모든 frame 이 충돌입니다."
            )
            return
        # Apply to sliders + push to viewer's live clip cache.
        self.apply_limits(result)
        self._push_limits_to_viewer()
        # 비교 toggle 활성화 — 이 시점부터 분석 전/후를 왔다갔다 비교 가능.
        self._limits_after_scan = {
            str(k): {"min": float(v.get("min", 0.0)),
                     "max": float(v.get("max", 0.0))}
            for k, v in result.items()
            if isinstance(v, dict)
        }
        self._showing_scan_result = True
        self._compare_btn.setEnabled(True)
        self._compare_btn.setText("↔ 분석 전과 비교")
        # 별창 비교도 이제 데이터가 있으니 활성화.
        self._compare_window_btn.setEnabled(True)

        diff_text = self._summarize_limits_diff(
            self._limits_before_scan or {}, self._limits_after_scan,
        )
        n = len(result)
        self._playback_status.setText(
            f"녹화 기반 안전 분석 완료 — '{label}' ({n_frames} frames, "
            f"{n} joints).  {diff_text}  ▶ 미리보기 로 비교 재생, [↔ 분석 "
            "전과 비교] 로 한계 toggle, [저장] 으로 control-service 영구화."
        )

    @staticmethod
    def _short_joint(name: str) -> str:
        """`openarm_left_joint2` → `L2`, `openarm_right_gripper_joint1` → `R-G1`."""
        import re
        side = "L" if "_left_" in name else "R" if "_right_" in name else "?"
        if "gripper" in name:
            m = re.search(r"gripper.*?(\d+)", name)
            return f"{side}-G{m.group(1) if m else ''}"
        m = re.search(r"joint[_]?(\d+)", name)
        return f"{side}{m.group(1)}" if m else name

    def _summarize_limits_diff(
        self,
        before: dict[str, dict[str, float]],
        after: dict[str, dict[str, float]],
    ) -> str:
        """분석 전/후 한계의 변화를 사람이 읽을 status 한 줄로 요약."""
        narrowed: list[tuple[str, float, float, float, float, float]] = []
        for name, a in after.items():
            b = before.get(name)
            if not b:
                continue
            try:
                b_lo, b_hi = float(b["min"]), float(b["max"])
                a_lo, a_hi = float(a["min"]), float(a["max"])
            except (KeyError, TypeError, ValueError):
                continue
            b_w = b_hi - b_lo
            a_w = a_hi - a_lo
            # ≥ 0.05 rad 좁아진 경우만 "narrowed" 로 카운트 (수치 노이즈 무시).
            if b_w - a_w > 0.05:
                narrowed.append((name, b_lo, b_hi, a_lo, a_hi, b_w - a_w))
        if not narrowed:
            return "변화 없음 (이미 안전 범위)."
        narrowed.sort(key=lambda x: x[5], reverse=True)
        top = narrowed[:3]
        parts = [
            f"{self._short_joint(n)} {b_lo:+.2f}↔{b_hi:+.2f} → "
            f"{a_lo:+.2f}↔{a_hi:+.2f}"
            for (n, b_lo, b_hi, a_lo, a_hi, _) in top
        ]
        rest = f" 외 {len(narrowed) - len(top)}개" if len(narrowed) > 3 else ""
        return f"{len(narrowed)}/{len(after)} joint 좁아짐 ─ " + ", ".join(parts) + rest

    def _compare_page_base_url(self) -> str:
        viewer_url = os.environ.get(
            "ADMIN_OPENARM_VIEWER_URL", self.DEFAULT_VIEWER_URL,
        )
        root = viewer_url.split("?", 1)[0].rstrip("/")
        return f"{root}/?embed=openarm-compare"

    def _focus_viewer_panel(self) -> None:
        """EduPing tab + 좌측 QWebEngineView 가 보이도록."""
        win = self.window()
        if win is not None and hasattr(win, "tabs"):
            win.tabs.setCurrentWidget(self)
        view = getattr(self, "viewer", None)
        if view is not None:
            view.show()
            view.raise_()

    def _navigate_viewer(self, url: str) -> None:
        """Load URL in the embedded web view (simulation panel)."""
        view = getattr(self, "viewer", None)
        if view is None:
            return
        qurl = QUrl(url)
        view.load(qurl)
        label = getattr(self, "_viewer_url_label", None)
        if label is not None:
            label.setText(url)

    def _compare_page_url(self, data_port: int) -> str:
        """Vite compare embed + localhost JSON server (PyQt QWebEngineView)."""
        base = self._compare_page_base_url()
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}data-port={data_port}"

    def _stop_compare_data_server(self) -> None:
        prev = getattr(self, "_compare_data_server", None)
        if prev is not None:
            try:
                prev.stop()
            except Exception:  # noqa: BLE001
                pass
            self._compare_data_server = None

    def _on_viewer_load_finished(self, ok: bool) -> None:
        if not ok:
            if getattr(self, "_viewer_compare_mode", False):
                self._playback_status.setText(
                    "비교 페이지 로드 실패 — robot-web 실행 확인 "
                    "(예: cd service/web-service/robot-web && npm run dev)"
                )
            return
        if getattr(self, "_viewer_compare_mode", False):
            pending = getattr(self, "_pending_compare_payload_json", None)
            if pending:
                view = getattr(self, "viewer", None)
                page = view.page() if view is not None else None
                if page is not None:
                    page.runJavaScript(
                        f"window.__ADMIN_COMPARE_DATA__ = {pending};"
                        "window.dispatchEvent(new Event('admin-compare-data'));"
                    )
                self._pending_compare_payload_json = None
            return
        pending = getattr(self, "_pending_compare_payload_json", None)
        if pending:
            view = getattr(self, "viewer", None)
            page = view.page() if view is not None else None
            if page is not None:
                page.runJavaScript(
                    f"window.__ADMIN_COMPARE_DATA__ = {pending};"
                    "window.dispatchEvent(new Event('admin-compare-data'));"
                )
            self._pending_compare_payload_json = None
            return
        self._push_limits_to_viewer()

    def _on_open_compare_in_viewer(self) -> None:
        """비교 페이지를 EduPing 탭 좌측 QWebEngineView(웹 브라우저)에 로드."""
        if (self._limits_before_scan is None
                or self._limits_after_scan is None):
            self._playback_status.setText(
                "먼저 [녹화 기반 안전 자동 탐색] 으로 비교할 한계를 만드세요."
            )
            return
        item = self._selected_routine()
        if item is None:
            self._playback_status.setText(
                "녹화 dropdown 에서 routine 을 선택하세요."
            )
            return

        self._focus_viewer_panel()

        view = getattr(self, "viewer", None)
        if view is None or not _HAS_WEBENGINE:
            QMessageBox.warning(
                self,
                "PyQtWebEngine 필요",
                "좌측 웹뷰어는 PyQt QWebEngineView 가 필요합니다.\n\n"
                "  pip install PyQtWebEngine\n"
                "또는 프로젝트 루트에서:\n"
                "  pip install -e .\n\n"
                "설치 후 admin 앱을 다시 실행하세요.",
            )
            self._playback_status.setText(
                "PyQtWebEngine 미설치 — pip install PyQtWebEngine 후 재시도."
            )
            return

        prev = getattr(self, "_compare_prepare_thread", None)
        if prev is not None and prev.isRunning():
            self._playback_status.setText(
                "이전 비교 준비가 진행 중입니다…"
            )
            return

        try:
            from services.compare_prepare import ComparePrepareThread
        except Exception as e:  # noqa: BLE001
            self._playback_status.setText(f"compare worker import 실패: {e!r}")
            return

        self._compare_window_btn.setEnabled(False)
        self._viewer_compare_mode = True
        self._exit_compare_btn.setEnabled(True)
        # Show compare embed immediately so the left panel visibly switches.
        self._navigate_viewer(self._compare_page_base_url())
        self._playback_status.setText(
            "비교 데이터 준비 중… 좌측 패널에 비교 화면을 띄웠습니다."
        )
        thread = ComparePrepareThread(
            item["path"],
            item.get("display_name", "?"),
            self._limits_before_scan,
            self._limits_after_scan,
            frame_hz=20.0,
            parent=self,
        )
        thread.finished_ok.connect(self._on_compare_prepare_ready)
        thread.finished_err.connect(self._on_compare_prepare_failed)
        thread.finished.connect(lambda: self._compare_window_btn.setEnabled(True))
        self._compare_prepare_thread = thread
        thread.start()

    def _on_compare_prepare_ready(self, _payload: dict, payload_json: str) -> None:
        view = getattr(self, "viewer", None)
        if view is None:
            self._playback_status.setText("웹뷰어 없음")
            return
        self._stop_compare_data_server()
        try:
            self._compare_data_server = _CompareDataServer(
                payload_json.encode("utf-8"),
            )
        except Exception as e:  # noqa: BLE001
            self._playback_status.setText(f"비교 데이터 서버 시작 실패: {e!r}")
            return
        data_port = self._compare_data_server.port
        full_url = self._compare_page_url(data_port)
        self._viewer_compare_mode = True
        # Qt WebEngine often blocks https→http data-port fetch; inject after load too.
        self._pending_compare_payload_json = payload_json
        self._exit_compare_btn.setEnabled(True)
        self._focus_viewer_panel()
        self._navigate_viewer(full_url)
        print(f"[ADMIN] compare QWebEngine URL: {full_url}", flush=True)
        self._playback_status.setText(
            f"좌측 시뮬레이션 패널에 비교 페이지 로드 중… {full_url}"
        )

    def _on_compare_prepare_failed(self, message: str) -> None:
        self._playback_status.setText(f"비교 준비 실패: {message}")

    def _on_exit_compare_viewer(self) -> None:
        """비교 페이지 종료 → 실시간 embed OpenArm 뷰어 URL 복귀."""
        if not getattr(self, "_viewer_compare_mode", False):
            return
        thread = getattr(self, "_compare_prepare_thread", None)
        if thread is not None and thread.isRunning():
            thread.wait(2000)
        self._viewer_compare_mode = False
        self._pending_compare_payload_json = None
        self._stop_compare_data_server()
        self._exit_compare_btn.setEnabled(False)
        view = getattr(self, "viewer", None)
        embed_url = getattr(self, "_viewer_embed_url", self.DEFAULT_VIEWER_URL)
        if view is not None:
            self._navigate_viewer(embed_url)
        self._playback_status.setText("실시간 OpenArm 뷰어로 복귀했습니다.")

    def _open_url_in_default_browser(self, url: str) -> str | None:
        """여러 launcher 를 차례로 시도. 성공하면 사용한 launcher 이름 반환.

        Linux 의 QDesktopServices.openUrl 은 xdg-open 에 의존하는데, 일부
        환경 (xdg-mime 설정 망가짐, argv 길이 초과 등) 에서 실패한다. Python
        표준 `webbrowser` 모듈은 다른 lookup 경로를 쓰므로 fallback 으로
        효과 있다.
        """
        # 1) Qt
        try:
            if QDesktopServices.openUrl(QUrl(url)):
                return "QDesktopServices"
        except Exception:  # noqa: BLE001
            pass
        # 2) Python webbrowser
        try:
            import webbrowser
            if webbrowser.open(url, new=2):
                return "webbrowser"
        except Exception:  # noqa: BLE001
            pass
        # 3) Linux xdg-open / macOS open / Windows start
        try:
            import shutil
            import subprocess
            for cmd in ("xdg-open", "open"):
                exe = shutil.which(cmd)
                if exe:
                    subprocess.Popen(
                        [exe, url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return cmd
        except Exception:  # noqa: BLE001
            pass
        return None

    def _on_toggle_limits_snapshot(self) -> None:
        """[↔ 분석 전과 비교] — 분석 전/후 한계 사이를 toggle.

        각 상태에서 ▶ 미리보기 를 누르면 viewer 가 그 한계로 clip 하므로 같은
        녹화가 자기충돌하는지/안 하는지 시각 비교 가능. 슬라이더 UI 도 즉시 그
        한계를 반영하고 viewer 의 live clip 캐시에도 push 한다.
        """
        if self._limits_before_scan is None or self._limits_after_scan is None:
            return
        if self._showing_scan_result:
            # Switch to "before" (original limits at scan time)
            self.apply_limits(self._limits_before_scan)
            self._push_limits_to_viewer()
            self._showing_scan_result = False
            self._compare_btn.setText("🔁 분석 결과 다시 적용")
            self._playback_status.setText(
                "분석 전 한계로 복원. ▶ 미리보기 를 눌러 비교 (이 한계에선 자기"
                "충돌이 보일 수 있음). 다시 누르면 안전 한계 복귀."
            )
        else:
            # Switch back to "after" (scan result)
            self.apply_limits(self._limits_after_scan)
            self._push_limits_to_viewer()
            self._showing_scan_result = True
            self._compare_btn.setText("↔ 분석 전과 비교")
            self._playback_status.setText(
                "안전 분석 결과 한계 재적용. ▶ 미리보기 로 다시 비교."
            )

    def _selected_routine(self) -> dict[str, str] | None:
        """현재 dropdown 에서 고른 routine item, 없으면 None."""
        if not getattr(self, "_routine_items", None):
            return None
        idx = self._routine_combo.currentIndex()
        if idx < 0 or idx >= len(self._routine_items):
            return None
        return self._routine_items[idx]

    def _on_safe_play(self) -> None:
        """현재 slider 한계를 control-service 로 push → 실물 재생 트리거.

        Backend (dance_stream) 가 매 frame 마다 동일 한계로 clip 하므로 실 motor 가
        slider 가 정한 안전 윈도우 밖으로 못 나간다. main.py 의 _on_safe_play_emitted
        slot 이 HTTP POST 처리.
        """
        item = self._selected_routine()
        if item is None:
            self._playback_status.setText("재생할 항목 선택 필요")
            return
        if item["kind"] == "mugunghwa":
            self._playback_status.setText(
                "무궁화 동작은 게임에서만 재생됩니다 (admin 실물 재생 미지원)",
            )
            return
        limits = self.collect_limits()
        payload = {
            "kind": item["kind"],
            "slug": item["slug"],
            "limits": limits,
        }
        self._playback_status.setText("실물 재생 요청 중…")
        self.safe_play_requested.emit(payload)

    def _on_save_safe_version(self) -> None:
        """원본은 보존하고 clip 본을 `<slug>-safe/` 디렉토리에 저장."""
        item = self._selected_routine()
        if item is None:
            self._playback_status.setText("저장할 항목 선택 필요")
            return
        try:
            from services.routine_playback import save_clipped_copy
        except Exception as e:  # noqa: BLE001
            self._playback_status.setText(f"저장 모듈 import 실패: {e!r}")
            return
        ok, msg = save_clipped_copy(
            source_path=item["path"],
            source_kind=item["kind"],
            source_slug=item["slug"],
            limits=self.collect_limits(),
        )
        # Refresh routine list so the new -safe entry appears in the combo box.
        if ok:
            self._reload_routine_list()
        self._playback_status.setText(msg)

    def _reload_routine_list(self) -> None:
        try:
            from services.routine_playback import list_routines
        except Exception:  # noqa: BLE001
            return
        prev = self._routine_combo.currentData()
        self._routine_items = list_routines()
        self._routine_combo.clear()
        if not self._routine_items:
            self._routine_combo.addItem("(녹화 파일 없음)")
            self._routine_combo.setEnabled(False)
            return
        self._routine_combo.setEnabled(True)
        new_idx = 0
        for i, it in enumerate(self._routine_items):
            self._routine_combo.addItem(
                f"[{it['kind']}] {it['display_name']}", it["path"],
            )
            if it["path"] == prev:
                new_idx = i
        self._routine_combo.setCurrentIndex(new_idx)

    def _refresh_playback_progress(self) -> None:
        """200ms tick — updates progress text + flips button state when the
        playback thread finishes on its own."""
        if self._playback is None:
            return
        if self._playback.is_playing:
            self._playback_status.setText(
                f"재생 {self._playback.progress_s:.1f} / "
                f"{self._playback.duration_s:.1f}s"
            )
        else:
            # Thread exited (either user-stopped or reached end). Reset buttons
            # AND lift the rclpy gate so the viewer goes back to live leader.
            if not self._play_btn.isEnabled():
                self._play_btn.setEnabled(True)
                self._stop_btn.setEnabled(False)
                self._playback_active = False
                self._playback_status.setText("정지 (leader 다시 활성)")

    # ------------------------------------------------- standalone joint-state pump
    def start_joint_subscriber(self) -> None:
        """Start the rclpy `/joint_states` subscriber + JS pump into the embedded
        viewer. Idempotent — second call is a no-op.

        Call when the EduPing tab is first activated (main.py wires this).
        """
        if self._joint_subscriber_started:
            return
        self._joint_subscriber_started = True
        try:
            from services.eduping_joint_subscriber import EdupingJointStateSubscriber
        except Exception as e:  # noqa: BLE001
            # services import failed — keep going; the viewer just won't update.
            return
        sub = EdupingJointStateSubscriber()
        ok = sub.start()
        if not ok:
            return
        self._joint_subscriber = sub
        # Qt cross-thread signal: rclpy spin → GUI thread.
        self._joint_state_received.connect(self._on_joint_state_main_thread)
        # Gate: when playback is active, drop live leader frames so the viewer
        # animates the recording exclusively (no flicker between two streams).
        sub.add_listener(
            lambda snap: (
                None if self._playback_active
                else self._joint_state_received.emit(snap)
            ),
        )

    def stop_joint_subscriber(self) -> None:
        if self._joint_subscriber is not None:
            try:
                self._joint_subscriber.stop()
            except Exception:  # noqa: BLE001
                pass
            self._joint_subscriber = None
        self._joint_subscriber_started = False

    def _push_limits_to_viewer(self) -> None:
        """Send the current slider state to the embedded page as joint limits.

        Embed page clips incoming leader positions to these ranges before
        rendering — gives the user immediate visual feedback when narrowing the
        safe range (no need to click 저장 to see the effect on the displayed arm).
        """
        view = getattr(self, "viewer", None)
        if view is None:
            return
        page = view.page()
        if page is None:
            return
        limits = self.collect_limits()
        try:
            payload = json.dumps(limits)
        except (TypeError, ValueError):
            return
        page.runJavaScript(
            f"if (window.setEdupingJointLimits) {{ window.setEdupingJointLimits({payload}); }}",
        )

    def _tick_label_update(self) -> None:
        """10 Hz consumer — reads the latest stashed snap and updates labels.

        Decoupled from the rclpy callback so 50 Hz publishing doesn't queue 50
        paint events per second across 16 QLabel widgets.
        """
        snap = self._latest_snap
        if snap is None:
            return
        self._update_current_joint_labels(snap)

    def _update_current_joint_labels(self, snap: dict) -> None:
        """Live update for the "현재" radian label in each joint row. Cheap
        QLabel.setText so we do this every frame, no throttle — keeps the
        readouts crisp even if the 3D pump skips frames.
        """
        names = snap.get("joint_names") or []
        positions = snap.get("positions") or []
        if not isinstance(names, list) or not isinstance(positions, list):
            return
        if len(names) != len(positions):
            return
        labels = self._joint_current_labels
        if not labels:
            return
        for joint_name, pos in zip(names, positions):
            label = labels.get(str(joint_name))
            if label is None:
                continue
            try:
                v = float(pos)
            except (TypeError, ValueError):
                continue
            # arm joints use "rad", finger uses "m" — show 3 decimals either way;
            # the absolute scale differs by ~2 orders of magnitude but the column
            # width is set so both fit.
            label.setText(f"{v:+.3f}")

    def _on_joint_state_main_thread(self, snap: dict) -> None:
        """Push the snapshot into the embedded page via window.setEdupingJointState.

        OpenarmViewer's `externalSnapshot` prop already accepts this shape — when
        set, it ignores the control-service WS and renders the provided pose.

        Throttled to 15 Hz. If newer snapshots arrive during the throttle window
        the most recent one wins (older ones are dropped — replay is realtime).
        Per-joint "현재" QLabel readouts are also throttled (10 Hz via a separate
        QTimer) so 50Hz rclpy doesn't spam paint events on 16 labels.
        """
        # Stash the latest snap; the 10Hz QTimer picks it up to update labels.
        self._latest_snap = snap
        if getattr(self, "_viewer_compare_mode", False):
            return
        view = getattr(self, "viewer", None)
        if view is None:
            return
        import time as _time
        now = _time.monotonic()
        if now - self._js_pump_last_mono < self._js_pump_min_interval_s:
            # Keep only the latest — older pending snap can be discarded.
            self._js_pump_pending = snap
            if not getattr(self, "_js_pump_flush_armed", False):
                self._js_pump_flush_armed = True
                # Schedule a flush exactly at the next allowed slot.
                ms = max(
                    1,
                    int((self._js_pump_min_interval_s
                         - (now - self._js_pump_last_mono)) * 1000),
                )
                QTimer.singleShot(ms, self._flush_pending_joint_state)
            return
        self._js_pump_last_mono = now
        self._js_pump_pending = None
        self._inject_joint_state(snap)

    def _flush_pending_joint_state(self) -> None:
        self._js_pump_flush_armed = False
        snap = self._js_pump_pending
        self._js_pump_pending = None
        if snap is None:
            return
        import time as _time
        self._js_pump_last_mono = _time.monotonic()
        self._inject_joint_state(snap)

    def _inject_joint_state(self, snap: dict) -> None:
        if getattr(self, "_viewer_compare_mode", False):
            return
        view = getattr(self, "viewer", None)
        if view is None:
            return
        page = view.page()
        if page is None:
            return
        try:
            payload = json.dumps(snap)
        except (TypeError, ValueError):
            return
        page.runJavaScript(
            f"if (window.setEdupingJointState) {{ window.setEdupingJointState({payload}); }}",
        )

    # ------------------------------------------------- 3D viewer JS bridge
    def _highlight_joint_in_viewer(self, joint_name: str) -> None:
        """Inject `window.highlightJoint('name')` into the embedded viewer page.

        No-op if the QWebEngineView isn't there (PyQtWebEngine missing) or if the
        embed page hasn't loaded yet. JavaScript escaping: joint names are static
        constants from _OPENARM_SPECS, no user input, so a basic JSON encode is
        enough.
        """
        view = getattr(self, "viewer", None)
        if view is None:
            return
        page = view.page()
        if page is None:
            return
        safe = json.dumps(joint_name)
        page.runJavaScript(
            f"if (window.highlightJoint) {{ window.highlightJoint({safe}); }}",
        )

    def _clear_joint_highlight_in_viewer(self) -> None:
        view = getattr(self, "viewer", None)
        if view is None:
            return
        page = view.page()
        if page is None:
            return
        page.runJavaScript(
            "if (window.clearJointHighlight) { window.clearJointHighlight(); }",
        )

    # ------------------------------------------------- 핸들러
    def _on_reset_clicked(self) -> None:
        defaults = _openarm_default_limits()
        for name, (min_box, max_box) in self._joint_widgets.items():
            d = defaults[name]
            # 순서 주의 — 먼저 Min 을 음수 끝으로 내려야 Max upper 가 정상 동작.
            min_box.setValue(d["min"])
            max_box.setValue(d["max"])
        self.save_status.setText("URDF 기본값으로 복원 — '저장' 눌러 적용")
        self.limits_reset_requested.emit()

    def _on_save_clicked(self) -> None:
        payload = self.collect_limits()
        self.save_status.setText("저장 중…")
        self.limits_save_requested.emit(payload)

    def collect_limits(self) -> dict[str, dict[str, float]]:
        return {
            name: {
                "min": float(min_box.value()),
                "max": float(max_box.value()),
            }
            for name, (min_box, max_box) in self._joint_widgets.items()
        }

    def apply_limits(self, limits: dict[str, dict[str, float]]) -> None:
        """외부(서버 GET 결과)에서 가져온 한계로 슬라이더를 채운다."""
        for name, (min_box, max_box) in self._joint_widgets.items():
            row = limits.get(name)
            if not row:
                continue
            try:
                lo = float(row.get("min", -_math.pi))
                hi = float(row.get("max", _math.pi))
            except (TypeError, ValueError):
                continue
            min_box.setValue(lo)
            max_box.setValue(hi)

    def set_save_status(self, ok: bool, msg: str) -> None:
        """`limits_save_requested` 처리 후 결과 메시지 갱신."""
        color = COLORS.get("success") if ok else "#c14545"
        self.save_status.setStyleSheet(
            f"color: {color}; font-size: 9pt; background: transparent;"
        )
        self.save_status.setText(msg)
