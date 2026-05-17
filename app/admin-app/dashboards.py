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
    QScrollArea,
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
# GogoPing — 자율주행
# --------------------------------------------------------------------------


class GogoPingDashboard(QWidget):
    NAME = "gogoping"

    def __init__(self, parent=None, stream_client=None):
        super().__init__(parent)
        self._stream_client = stream_client

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

        host_lay = QVBoxLayout(self)
        host_lay.setContentsMargins(0, 0, 0, 0)
        host_lay.setSpacing(0)
        host_lay.addWidget(scroll)

        content = QWidget()
        content.setObjectName("dashContent")
        scroll.setWidget(content)

        outer = QVBoxLayout(content)
        outer.setContentsMargins(28, 20, 28, 24)
        outer.setSpacing(14)

        # ── 헤더 행: 로고 + 이름 | 시스템 stat 칩들 | 상태 뱃지 ───
        # 칩을 헤더 빈 공간으로 흡수해 세로 공간을 카메라/맵에 양보.
        meta = ROBOTS[self.NAME]
        accent = meta["color"]

        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        avatar = QWidget()
        avatar.setFixedSize(56, 56)
        avatar.setStyleSheet(
            f"background: {meta['color_soft']}; border-radius: 28px;"
        )
        a_lay = QVBoxLayout(avatar)
        a_lay.setContentsMargins(0, 0, 0, 0)
        a_lay.addWidget(Icon(meta["icon"], size=30, color=accent),
                        0, Qt.AlignCenter)
        header_row.addWidget(avatar)

        name_lbl = QLabel(meta["name"])
        name_lbl.setStyleSheet(
            f"font-size: 22px; font-weight: 800; color: {COLORS['text']};"
        )
        header_row.addWidget(name_lbl, 0, Qt.AlignVCenter)

        # 칩들 — 헤더 옆 빈 공간을 채운다
        self.battery_chip = StatChip(
            "battery", "배터리", "74%", COLORS["mint"],
            with_bar=True, battery=True,
        )
        self.battery_chip.set_pct(74)
        self.cpu_chip = StatChip("cpu", "CPU", "31%", COLORS["warning"])
        self.lidar_chip = StatChip("radar", "LiDAR", "12 Hz", COLORS["lavender"])
        self.localizer_chip = StatChip(
            "pin", "위치 신뢰도", "98%", COLORS["sky"],
        )
        self.distance_chip = StatChip(
            "vehicle", "오늘 주행", "1.42 km", COLORS["sun"],
        )
        for chip in (self.battery_chip, self.cpu_chip, self.lidar_chip,
                     self.localizer_chip, self.distance_chip):
            chip.setMinimumHeight(60)
            header_row.addWidget(chip, 1)

        self.header_badge = StatusBadge("정상 작동", COLORS["success"])
        header_row.addWidget(self.header_badge, 0, Qt.AlignVCenter)

        outer.addLayout(header_row)

        from widgets.lidar_scan_view import LidarScanView
        from widgets.odom_compact import OdomCompact

        # ── 4분면 2×2 grid ──
        quad = QGridLayout()
        quad.setHorizontalSpacing(14)
        quad.setVerticalSpacing(14)

        # 좌상: 카메라
        self.camera_card = Card("전방 카메라")
        if stream_client is not None:
            self.camera = CameraStreamView(
                robot=self.NAME, stream_client=stream_client, stream_id=0,
            )
        else:
            self.camera = CameraView()
        self.camera_card.body.addWidget(self.camera, 1)
        quad.addWidget(self.camera_card, 0, 0)

        # 우상: 실내 맵
        control_url = os.environ.get(
            "PINGDER_CONTROL_URL", "http://localhost:8000",
        )
        self.map_card = WaypointMapCard(control_url=control_url)
        quad.addWidget(self.map_card, 0, 1)

        # 좌하: LiDAR 단독
        self.lidar_view = LidarScanView()
        self.lidar_card = Card("LiDAR · 실시간 스캔")
        self.lidar_card.body.addWidget(self.lidar_view, 1)
        quad.addWidget(self.lidar_card, 1, 0)

        # 우하: ODOM (위) + Teleop + CameraPan (세로 stack) — 한 셀 안 분할
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

        self.odom_compact = OdomCompact()
        self.odom_card = Card("ODOM")
        self.odom_card.body.addWidget(self.odom_compact, 1)
        self.odom_card.setFixedHeight(120)

        rb_lay = QVBoxLayout()
        rb_lay.setContentsMargins(0, 0, 0, 0)
        rb_lay.setSpacing(10)
        rb_lay.addWidget(self.odom_card, 0)
        rb_lay.addWidget(self.teleop_card, 1)
        rb_lay.addWidget(self.camera_pan_card, 1)
        quad.addLayout(rb_lay, 1, 1)

        quad.setColumnStretch(0, 1)
        quad.setColumnStretch(1, 1)
        quad.setRowStretch(0, 1)
        quad.setRowStretch(1, 1)

        outer.addLayout(quad, 1)

        # WS state 라우팅 — Dashboard 가 단일 수신점
        self.teleop_client.connect_state_ws(self.on_state)
        self.camera_pan_client.connect_state_ws(self.camera_pan_card.on_state)

        self._tick = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(60)

    def update_battery(self, level: float) -> None:
        """``/gogoping/state`` snapshot 의 battery_level 을 받아 헤더 chip + 시스템 카드 바 갱신.

        main.py 의 state_client 콜백이 snapshot.get("battery_level") 추출 후 호출.
        """
        pct = max(0, min(100, int(round(level))))
        self.battery_chip.set_value(f"{pct}%")
        self.battery_chip.set_pct(pct)
        self.battery.set_pct(pct)

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
            if age_ms > 500 or hz <= 0 or not ranges:
                self.lidar_chip.set_value("—")
            else:
                self.lidar_chip.set_value(f"{hz:.1f} Hz")
        else:
            self.lidar_chip.set_value("—")

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

        if self._tick % 30 == 0:
            self.cpu_chip.set_value(f"{random.randint(28, 38)}%")
            self.distance_chip.set_value(
                f"{1.42 + (self._tick // 30) * 0.003:.2f} km"
            )


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
