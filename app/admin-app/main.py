"""Pingdergarten Admin UI 진입점.

TopBar (전역 헤더) + 상단 가로 탭바 (QTabWidget) — GogoPing / EduPing 두 탭.
이전엔 단일 GogoPing 페이지였으나 EduPing OpenArm 관절 범위 튜닝 UI 가 필요해
다시 탭 구조로 복귀. 시계는 TopBar 우측 (BT state 왼쪽).
"""

from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from datetime import datetime

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config.client_id import get_or_create_client_id
from dashboards import EduPingControlDashboard, GogoPingDashboard
from services.nav_debug_client import NavDebugClient
from services.state_client import StateClient
from services.stream_client import StreamClient
from theme import COLORS, ROBOTS, apply_theme
from widgets import Icon, StatChip, StatusBadge
from widgets.bt_state_inline import BTStateInline


def _detect_sim_mode() -> bool:
    """Control Server /teleop/health 의 mode 가 'sim' 인지. 실패 시 False (실물 가정)."""
    try:
        import httpx
        r = httpx.get("http://localhost:8000/teleop/health", timeout=0.5)
        if r.status_code != 200:
            return False
        return r.json().get("mode") == "sim"
    except Exception:
        return False


def _format_duration(seconds: float) -> str:
    """초 단위 → 한국어 시/분/초 표기. idle_chip 카운트다운용.

    - >= 1시간: ``"23시간 59분 45초"``
    - >= 1분:   ``"5분 30초"``
    - 미만:    ``"45초"``
    - 0 이하:  ``"0초"``
    """
    s = max(0, int(round(seconds)))
    if s >= 3600:
        return f"{s // 3600}시간 {(s % 3600) // 60}분 {s % 60}초"
    if s >= 60:
        return f"{s // 60}분 {s % 60}초"
    return f"{s}초"


class TopBar(QWidget):
    """본문 상단 — 페이지 타이틀 + 시계 + BT 상태 + 시스템 뱃지.

    레이아웃 (좌→우):
        [아이콘] [GogoPing 대시보드]   [13:57:32 / 날짜]   [BTStateInline]   [badges]
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(100)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(28, 12, 28, 10)
        lay.setSpacing(16)

        # 좌측 아이콘 — 활성 탭에 따라 갱신 (set_active_robot 호출).
        self._icon_meta = ROBOTS["gogoping"]
        self.icon_box = QFrame()
        self.icon_box.setFixedSize(40, 40)
        self.icon_box.setStyleSheet(
            f"background: {COLORS['panel']}; border-radius: 20px; "
            f"border: 1px solid {COLORS['border']};"
        )
        ib = QVBoxLayout(self.icon_box)
        ib.setContentsMargins(0, 0, 0, 0)
        self.icon = Icon(self._icon_meta["icon"], size=22, color=self._icon_meta["color"])
        ib.addWidget(self.icon, 0, Qt.AlignCenter)
        lay.addWidget(self.icon_box)

        # 타이틀 — 활성 탭에 따라 갱신.
        self.title = QLabel(f"{self._icon_meta['name']} 대시보드")
        f = QFont()
        f.setPointSize(18)
        f.setBold(True)
        self.title.setFont(f)
        lay.addWidget(self.title)
        lay.addSpacing(8)

        # 시계 — 타이틀 오른쪽, BT state 왼쪽. 시간 (큰 글씨) + 날짜 (작은 글씨) 두 줄.
        clock_box = QVBoxLayout()
        clock_box.setSpacing(0)
        clock_box.setContentsMargins(0, 0, 0, 0)
        self.clock = QLabel("--:--:--")
        self.clock.setStyleSheet(
            f"font-size: 16pt; font-weight: 800; color: {COLORS['text']}; "
            f"background: transparent;"
        )
        self.date = QLabel(datetime.now().strftime("%Y-%m-%d %a"))
        self.date.setStyleSheet(
            f"font-size: 9pt; color: {COLORS['text_muted']}; "
            f"background: transparent;"
        )
        clock_box.addWidget(self.clock)
        clock_box.addWidget(self.date)
        lay.addLayout(clock_box)
        lay.addSpacing(12)

        # BT state inline (GogoPing 전용 디버그)
        self.bt_state = BTStateInline()
        lay.addWidget(self.bt_state, 0, Qt.AlignVCenter)

        lay.addStretch(1)

        # IDLE → RETURNING 자동 복귀 카운트다운 chip + 인라인 조정 slider.
        # IDLE 중에만 chip 카운트다운 진행, slider 도 IDLE 중에만 enabled.
        self._idle_remaining_s: float | None = None
        self._idle_total_s: float | None = None
        self._idle_is_idle: bool = False
        # state_client 는 AdminWindow 가 _wire_signals 단계에서 setter 로 주입.
        self._idle_apply_cb: "Callable[[float], None] | None" = None

        # 컨테이너 (수직: chip + slider row)
        idle_box = QWidget()
        idle_v = QVBoxLayout(idle_box)
        idle_v.setContentsMargins(0, 0, 0, 0)
        idle_v.setSpacing(2)

        self.idle_chip = StatChip(
            "pin", "복귀까지", "—", COLORS["lavender"],
            with_bar=False,
        )
        self.idle_chip.setMinimumWidth(260)
        self.idle_chip.setMaximumWidth(300)
        self.idle_chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        idle_v.addWidget(self.idle_chip)

        # 조정 slider row — slider (1~3600초, step 5) + 라벨 + 적용 버튼.
        # IDLE 일 때만 enabled. 적용 클릭 시 state_client.post_idle_timeout 호출.
        slider_row = QHBoxLayout()
        slider_row.setContentsMargins(4, 0, 4, 0)
        slider_row.setSpacing(4)
        self.idle_slider = QSlider(Qt.Horizontal)
        self.idle_slider.setRange(1, 3600)
        self.idle_slider.setSingleStep(5)
        self.idle_slider.setPageStep(60)
        self.idle_slider.setValue(60)
        self.idle_slider.setEnabled(False)
        self.idle_slider.setMinimumWidth(120)
        self.idle_slider_label = QLabel("1분")
        self.idle_slider_label.setStyleSheet(
            f"font-size: 8pt; color: {COLORS['text_soft']}; min-width: 56px;"
        )
        self.idle_slider_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.idle_apply_btn = QPushButton("적용")
        self.idle_apply_btn.setEnabled(False)
        self.idle_apply_btn.setCursor(Qt.PointingHandCursor)
        self.idle_apply_btn.setStyleSheet(
            f"QPushButton {{ background: {COLORS['lavender']}; color: white; "
            f"border: none; border-radius: 4px; padding: 2px 8px; "
            f"font-size: 8pt; font-weight: 700; }}"
            f"QPushButton:disabled {{ background: {COLORS['border']}; color: {COLORS['text_muted']}; }}"
        )
        self.idle_slider.valueChanged.connect(self._on_idle_slider_changed)
        self.idle_apply_btn.clicked.connect(self._on_idle_apply_clicked)
        slider_row.addWidget(self.idle_slider, 1)
        slider_row.addWidget(self.idle_slider_label, 0)
        slider_row.addWidget(self.idle_apply_btn, 0)
        idle_v.addLayout(slider_row)

        idle_box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        idle_box.setMaximumWidth(300)
        lay.addWidget(idle_box, 0, Qt.AlignVCenter)

        # 배터리 chip — 본문 chip 행에서 이쪽으로 이동. % 바 포함, 폭 제한.
        self.battery_chip = StatChip(
            "battery", "배터리", "--%", COLORS["mint"],
            with_bar=True, battery=True,
        )
        self.battery_chip.setMaximumWidth(180)
        self.battery_chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        lay.addWidget(self.battery_chip, 0, Qt.AlignVCenter)

        # 상태 뱃지
        self.network_badge = StatusBadge("ROS2 연결", COLORS["sky"])
        self.system_badge = StatusBadge("시스템 정상", COLORS["success"])
        lay.addWidget(self.network_badge)
        lay.addWidget(self.system_badge)

        # 1Hz tick
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._tick()

    def _tick(self) -> None:
        now = datetime.now()
        self.clock.setText(now.strftime("%H:%M:%S"))
        # 날짜는 자정 넘어가야만 갱신되지만 비용 없으므로 매초 setText 유지
        self.date.setText(now.strftime("%Y-%m-%d %a"))
        # IDLE 카운트다운 — snapshot 도착 사이 1초씩 차감. 0 이하면 그대로 유지 (FSM 이
        # idle_timeout trigger 발화하면 다음 snapshot 에서 remaining=None 으로 비활성).
        if self._idle_remaining_s is not None:
            self._idle_remaining_s = max(0.0, self._idle_remaining_s - 1.0)
        self._refresh_idle_chip()

    def _refresh_idle_chip(self) -> None:
        """idle_chip 값 갱신 — IDLE 중이면 카운트다운, 아니면 totals 또는 비활성."""
        if self._idle_remaining_s is not None:
            self.idle_chip.set_value(_format_duration(self._idle_remaining_s))
        elif self._idle_total_s is not None:
            self.idle_chip.set_value(_format_duration(self._idle_total_s))
        else:
            self.idle_chip.set_value("—")

    def update_idle_countdown(
        self, remaining: float | None, total: float | None
    ) -> None:
        """``/gogoping/state`` snapshot 의 idle_seconds_remaining / idle_timeout_seconds
        반영. remaining=None → IDLE 아님 (totals 만 표시, slider 비활성).
        total=None → 모니터 미동작."""
        self._idle_remaining_s = remaining
        self._idle_total_s = total
        # IDLE 여부 — remaining 이 float 이면 IDLE 중 (snapshot.fsm_state == "IDLE").
        # slider/적용 버튼 enable 토글.
        is_idle = remaining is not None
        if is_idle != self._idle_is_idle:
            self._idle_is_idle = is_idle
            self.idle_slider.setEnabled(is_idle)
            self.idle_apply_btn.setEnabled(is_idle)
            # IDLE 진입 시 slider 를 현재 total 값으로 동기화 (사용자 직관성).
            # IDLE 떠나면 slider 위치는 그대로 유지 — 다음 IDLE 진입 시 이어서.
            if is_idle and total is not None:
                clamped = max(1, min(3600, int(round(total))))
                self.idle_slider.blockSignals(True)
                self.idle_slider.setValue(clamped)
                self.idle_slider.blockSignals(False)
                self._refresh_idle_slider_label()
        self._refresh_idle_chip()

    def _refresh_idle_slider_label(self) -> None:
        self.idle_slider_label.setText(_format_duration(float(self.idle_slider.value())))

    def _on_idle_slider_changed(self, _v: int) -> None:
        self._refresh_idle_slider_label()

    def _on_idle_apply_clicked(self) -> None:
        """적용 버튼 — state_client.post_idle_timeout 호출. apply_cb 미주입이면 no-op."""
        if self._idle_apply_cb is None:
            return
        seconds = float(self.idle_slider.value())
        try:
            self._idle_apply_cb(seconds)
        except Exception:
            logger.exception("idle_timeout apply 콜백 실패") if "logger" in globals() else None

    def set_idle_apply_callback(self, cb: "Callable[[float], None]") -> None:
        """AdminWindow._wire_signals 에서 state_client.post_idle_timeout 주입."""
        self._idle_apply_cb = cb

    def update_battery(self, level: float) -> None:
        """``/gogoping/state`` snapshot 의 battery_level 반영 — chip value + % bar."""
        pct = max(0, min(100, int(round(level))))
        self.battery_chip.set_value(f"{pct}%")
        self.battery_chip.set_pct(pct)

    def set_active_robot(self, robot_key: str) -> None:
        """탭 변경 시 호출 — 아이콘/타이틀/로봇별 전용 위젯(BT, 배터리) 표시 토글.

        GogoPing 전용 위젯 (BTStateInline, 배터리 chip) 은 EduPing 탭에선 숨김 —
        해당 로봇 데이터가 아직 없어 stale 정보를 보여주는 것보다 깔끔.
        """
        if robot_key not in ROBOTS:
            return
        meta = ROBOTS[robot_key]
        self._icon_meta = meta
        # 아이콘 위젯 교체 — Icon 은 setter 가 없어 새 위젯 생성 후 swap.
        ib_layout = self.icon_box.layout()
        if ib_layout is not None:
            while ib_layout.count() > 0:
                item = ib_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
            self.icon = Icon(meta["icon"], size=22, color=meta["color"])
            ib_layout.addWidget(self.icon, 0, Qt.AlignCenter)
        self.title.setText(f"{meta['name']} 대시보드")
        # GogoPing 전용 위젯은 gogoping 탭에서만 표시.
        is_gogoping = robot_key == "gogoping"
        self.bt_state.setVisible(is_gogoping)
        self.battery_chip.setVisible(is_gogoping)


class AdminWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pingdergarten Admin")
        self.resize(1400, 880)
        self.setMinimumSize(1180, 760)

        # SR-CAM-004 — 단일 StreamClient 인스턴스 (앱 라이프타임).
        # base_url 은 STREAMING_BASE_URL env 로 override 가능.
        # SIM 모드면 실물 카메라 송출이 없으므로 StreamClient 를 띄우지 않고
        # GogoPingDashboard 의 mock CameraView 로 fallback.
        if _detect_sim_mode():
            self.stream_client = None
        else:
            client_id = get_or_create_client_id()
            base_url = os.environ.get("STREAMING_BASE_URL", "ws://localhost:8100")
            self.stream_client = StreamClient(
                client_id=client_id, base_url=base_url, client_kind="admin",
            )
            self.stream_client.start()

        root = QWidget()
        root.setObjectName("mainBg")
        self.setCentralWidget(root)
        root_lay = QVBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        self.topbar = TopBar()
        root_lay.addWidget(self.topbar)

        # 가로 탭바 — GogoPing / EduPing. QTabWidget 자체가 탭바를 상단에 그리므로
        # 별도 nav row 없이 그대로 활용. 기본 탭은 너무 작아서 (~10pt 폰트, 좁은 padding)
        # 잘 안 보이는 문제 — stylesheet 로 폰트·padding·min-width 모두 키운다.
        self.tabs = QTabWidget()
        self.tabs.setObjectName("adminTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.setStyleSheet(
            "QTabWidget#adminTabs::pane {"
            f"  border: 1px solid {COLORS['border']};"
            "  border-top: none;"
            "  background: " + COLORS["panel"] + ";"
            "}"
            "QTabWidget#adminTabs > QTabBar {"
            "  qproperty-drawBase: 0;"
            "}"
            "QTabWidget#adminTabs QTabBar::tab {"
            "  font-size: 14pt;"
            "  font-weight: 700;"
            "  padding: 14px 36px;"
            "  min-width: 200px;"
            f"  color: {COLORS['text_muted']};"
            f"  background: {COLORS['bg']};"
            f"  border: 1px solid {COLORS['border']};"
            "  border-top-left-radius: 12px;"
            "  border-top-right-radius: 12px;"
            "  margin-right: 4px;"
            "}"
            "QTabWidget#adminTabs QTabBar::tab:selected {"
            f"  color: {COLORS['text']};"
            f"  background: {COLORS['panel']};"
            "  border-bottom-color: " + COLORS["panel"] + ";"
            "}"
            "QTabWidget#adminTabs QTabBar::tab:hover:!selected {"
            f"  color: {COLORS['text']};"
            "}"
        )

        self.gogoping_dashboard = GogoPingDashboard(stream_client=self.stream_client)
        self.gogoping_dashboard.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tabs.addTab(self.gogoping_dashboard, "GogoPing")

        self.eduping_dashboard = EduPingControlDashboard()
        self.eduping_dashboard.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tabs.addTab(self.eduping_dashboard, "EduPing")

        # Eagerly start the rclpy subscriber + push initial limits to the viewer
        # NOW (at app init) rather than waiting for the user to click the EduPing
        # tab. This gives the Three.js scene + leader stream a head start so
        # the first tab-click is instant.
        # The QWebEngineView itself starts loading its URL the moment we set
        # setUrl() in EduPingControlDashboard.__init__, regardless of whether
        # the tab is currently visible.
        try:
            self.eduping_dashboard.start_joint_subscriber()
        except Exception:
            pass

        self.tabs.currentChanged.connect(self._on_tab_changed)
        root_lay.addWidget(self.tabs, 1)

        # 첫 탭(GogoPing) 의 robot key 로 TopBar 초기화.
        self.topbar.set_active_robot("gogoping")

        # 하위 호환용 — 기존 코드가 self.dashboard 참조한 부분 일부 남아있을 수 있음.
        self.dashboard = self.gogoping_dashboard

        # /ws/robot-state 구독 — gogoping_modes 의 BT 상태가 topbar.bt_state 로 흘러감.
        # control-server base URL 은 PINGDER_CONTROL_URL 환경변수 우선.
        control_url = os.environ.get("PINGDER_CONTROL_URL", "http://localhost:8000")
        self.state_client = StateClient(base_url=control_url)
        # BTStateInline (topbar) + GogoPingDashboard 둘 다 snapshot 으로 갱신
        self.state_client.connect(self._on_robot_state)

        # /ws/nav-debug-events 구독 — Dashboard DebugDrawer 의 NavDebugLogCard 로 흘러감.
        # cancel chain (SetGoal → reconcile → FSM → BT swap → NavTo → graph_router) 추적.
        self.nav_debug_client = NavDebugClient(base_url=control_url)
        self.nav_debug_client.connect(self.dashboard.nav_debug_log.append_event)

        # 디버그 패널 (Dashboard 우측 DebugDrawer) → state_client.post_force_state
        self.dashboard.debug_panel.force_state_requested.connect(
            lambda state: self.state_client.post_force_state(
                state,
                on_result=self.dashboard.debug_panel.set_last_result,
            )
        )

        # 긴급정지 버튼 → state_client.post_emergency_stop
        self.dashboard.debug_panel.emergency_stop_requested.connect(
            lambda: self.state_client.post_emergency_stop(
                on_result=self.dashboard.debug_panel.set_estop_result,
            )
        )

        # [순찰] 빠른 버튼 → state_client.post_patrol (control-server 가 랜덤 그룹 선택)
        self.dashboard.debug_panel.patrol_requested.connect(
            lambda: self.state_client.post_patrol(
                on_result=self.dashboard.debug_panel.set_patrol_result,
            )
        )

        # 배터리 디버그 슬라이더 → state_client.post_battery_level
        self.dashboard.battery_debug.battery_level_requested.connect(
            lambda level: self.state_client.post_battery_level(
                level,
                on_result=self.dashboard.battery_debug.set_last_result,
            )
        )

        # PoseDebugPanel → state_client.post_robot_pose
        self.dashboard.pose_debug.pose_override_requested.connect(
            lambda x, y, yaw, clear: self.state_client.post_robot_pose(
                x, y, yaw, clear=clear,
                on_result=self.dashboard.pose_debug.set_last_result,
            )
        )

        # EduPing 관절 한계 — 슬라이더 저장 버튼이 Control Server POST 트리거.
        self.eduping_dashboard.limits_save_requested.connect(
            self._save_eduping_joint_limits,
        )
        # 안전 실물 재생 — limits POST + play POST 를 background 에서.
        self.eduping_dashboard.safe_play_requested.connect(
            self._safe_play_eduping_routine,
        )

        # TopBar idle_timeout slider 적용 → state_client.post_idle_timeout
        self.topbar.set_idle_apply_callback(
            lambda seconds: self.state_client.post_idle_timeout(seconds)
        )

    def _on_tab_changed(self, index: int) -> None:
        # 탭 인덱스 → ROBOTS key 매핑 (탭 add 순서 그대로).
        robot_key = "gogoping" if index == 0 else "eduping"
        self.topbar.set_active_robot(robot_key)
        if robot_key == "eduping":
            # 슬라이더 한 번만 백그라운드 로드. control-service 없으면 조용히 fallback.
            if not getattr(self, "_eduping_limits_loaded", False):
                self._load_eduping_joint_limits()
                self._eduping_limits_loaded = True

    def _control_base_url(self) -> str:
        return os.environ.get("PINGDER_CONTROL_URL", "http://localhost:8000")

    def _load_eduping_joint_limits(self) -> None:
        """Best-effort background fetch of saved limits from the control-service.

        Silent failure — the slider just stays at URDF defaults if the server is
        unreachable. The 3D viewer doesn't need this at all (it goes direct via
        rclpy), so this is only relevant when the user wants to *save* limits.
        """
        import threading

        def _work() -> None:
            try:
                import httpx
                r = httpx.get(
                    f"{self._control_base_url()}/api/eduping/joint-limits",
                    timeout=1.5,
                )
                if r.status_code != 200:
                    return
                data = r.json()
                limits = data.get("limits") or {}
                if not isinstance(limits, dict):
                    return
                # Marshal back to GUI thread via Qt's invokeMethod indirection.
                self.eduping_dashboard.apply_limits(limits)
            except Exception:
                # No popup, no banner — silent. Defaults stay in place.
                return

        threading.Thread(target=_work, name="eduping-limits-load", daemon=True).start()

    def _safe_play_eduping_routine(self, payload: dict) -> None:
        """payload = {kind, slug, limits}. Background thread:
        1) POST current limits to control-service (so dance_stream clipping
           uses the values currently shown in the admin sliders).
        2) POST play with target=real — control-service streams the (clipped)
           trajectory to the follower controller.
        Status text on the dashboard is updated with the result.
        """
        import threading

        kind = str(payload.get("kind") or "")
        slug = str(payload.get("slug") or "")
        limits = payload.get("limits") or {}
        if kind not in ("dance", "greeting") or not slug:
            self.eduping_dashboard._playback_status.setText(
                "재생 요청 payload 오류",
            )
            return

        def _work() -> None:
            try:
                import httpx
                base = self._control_base_url()
                # 1) limits push
                r = httpx.post(
                    f"{base}/api/eduping/joint-limits",
                    json={"limits": limits},
                    timeout=3.0,
                )
                if r.status_code != 200:
                    self.eduping_dashboard._playback_status.setText(
                        f"한계 push 실패 — HTTP {r.status_code}",
                    )
                    return
                # 2) play
                play_url = (
                    f"{base}/api/eduping/{kind}/{slug}/play"
                )
                r2 = httpx.post(
                    play_url,
                    json={"target": "real", "speed": 1.0},
                    timeout=5.0,
                )
                if r2.status_code == 200:
                    self.eduping_dashboard._playback_status.setText(
                        f"실물 재생 시작: {kind}/{slug}",
                    )
                else:
                    self.eduping_dashboard._playback_status.setText(
                        f"재생 실패 — HTTP {r2.status_code} ({r2.text[:80]})",
                    )
            except Exception as e:
                self.eduping_dashboard._playback_status.setText(
                    f"Control Server 미연결: {e} "
                    "(port 8000 의 control-service 실행 확인)",
                )

        threading.Thread(target=_work, name="eduping-safe-play", daemon=True).start()

    def _save_eduping_joint_limits(self, limits: dict) -> None:
        """POST limits in a background thread — only path that surfaces errors,
        because the user explicitly clicked '저장' and expects feedback.
        """
        import threading

        def _work() -> None:
            try:
                import httpx
                r = httpx.post(
                    f"{self._control_base_url()}/api/eduping/joint-limits",
                    json={"limits": limits},
                    timeout=2.5,
                )
                if r.status_code == 200:
                    self.eduping_dashboard.set_save_status(True, "저장 완료")
                else:
                    self.eduping_dashboard.set_save_status(
                        False, f"저장 실패 — HTTP {r.status_code}",
                    )
            except Exception as e:
                self.eduping_dashboard.set_save_status(False, f"저장 실패: {e}")

        threading.Thread(target=_work, name="eduping-limits-save", daemon=True).start()

    def _on_robot_state(self, snap: dict) -> None:
        """``/ws/robot-state`` snapshot 단일 수신점. BTStateInline + GogoPingDashboard 분배.

        daemon thread 에서 호출 — 위젯 갱신은 setText / set_pct 류 단순 호출만이라
        BTStateInline 의 update_snapshot 과 동일 위험 패턴 (기존 코드 일치).
        """
        self.topbar.bt_state.update_snapshot(snap)

        level = snap.get("battery_level")
        if level is not None:
            try:
                self.topbar.update_battery(float(level))
            except Exception:
                pass

        # IDLE → RETURNING 카운트다운. 둘 다 키 자체가 있을 때만 갱신 — 옛 노드/스키마와
        # forward-compat. remaining=None 은 "IDLE 아님" 정상 값이므로 None 도 그대로 전달.
        if "idle_seconds_remaining" in snap or "idle_timeout_seconds" in snap:
            try:
                self.topbar.update_idle_countdown(
                    snap.get("idle_seconds_remaining"),
                    snap.get("idle_timeout_seconds"),
                )
            except Exception:
                pass

        pose = snap.get("robot_pose")
        if pose is not None:
            try:
                self.dashboard.update_pose(pose)
            except Exception:
                pass

        # in_map 은 키 자체가 있으면 (None 포함) 갱신 — UNKNOWN 표시 토글 위해
        if "in_map" in snap:
            try:
                self.dashboard.update_map_status(snap["in_map"])
            except Exception:
                pass

        # patrol 진행 시각화 — waypoint_map_card 의 vertex 번호/X
        if "patrol" in snap:
            try:
                self.dashboard.map_card.update_patrol(snap.get("patrol"))
            except Exception:
                pass

    def closeEvent(self, ev) -> None:   # noqa: N802
        if self.stream_client is not None:
            try:
                self.stream_client.stop()
            except Exception:
                pass
        try:
            self.state_client.stop()
        except Exception:
            pass
        try:
            self.nav_debug_client.stop()
        except Exception:
            pass
        try:
            self.eduping_dashboard.stop_joint_subscriber()
        except Exception:
            pass
        try:
            playback = getattr(self.eduping_dashboard, "_playback", None)
            if playback is not None:
                playback.stop()
        except Exception:
            pass
        super().closeEvent(ev)


def main() -> int:
    from webengine_gpu import apply_chromium_gpu_flags

    apply_chromium_gpu_flags()
    app = QApplication(sys.argv)
    app.setApplicationName("Pingdergarten Admin")
    apply_theme(app)
    win = AdminWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
