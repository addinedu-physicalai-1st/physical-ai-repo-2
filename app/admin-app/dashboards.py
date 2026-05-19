"""세 로봇 대시보드. 모두 가짜 데이터 + QTimer 로 살아있는 느낌만 흉내낸다.

이모지 대신 Icon / IconText / TaskQueue 의 아이콘 kind 를 쓴다.
"""

from __future__ import annotations

import math
import os
import random

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

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
from widgets.camera_widget import CameraStreamView
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

    panel 안에는 DebugStatePanel / BatteryDebugSlider / PoseDebugPanel 3개가 세로
    stack. 토글 버튼 (◂/▸) 클릭 시 panel 만 show/hide — 버튼 자체는 항상 노출되어
    다시 펼칠 수 있다. 초기 상태: 펼침 (open=True).
    """

    PANEL_WIDTH = 300
    TOGGLE_WIDTH = 36

    def __init__(self, debug_panel, battery_debug, pose_debug, parent=None):
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
        panel_lay.addStretch(1)
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
        from widgets.pose_debug_panel import PoseDebugPanel
        self.debug_panel = DebugStatePanel()
        self.battery_debug = BatteryDebugSlider()
        self.pose_debug = PoseDebugPanel()

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
        if stream_client is not None:
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
