"""Pingdergarten Admin UI 진입점.

GogoPing 전용 단일 페이지 대시보드. 이전엔 좌측 사이드바로 GogoPing/NoriArm/Eduping
3개 페이지를 전환했으나, UI 개편으로 사이드바를 제거하고 GogoPing 한 페이지만 노출.
시계는 TopBar 우측 (BT state 왼쪽) 으로 이동.
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
    QVBoxLayout,
    QWidget,
)

from config.client_id import get_or_create_client_id
from dashboards import GogoPingDashboard
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

        # 좌측 아이콘 (GogoPing 고정)
        meta = ROBOTS["gogoping"]
        self.icon_box = QFrame()
        self.icon_box.setFixedSize(40, 40)
        self.icon_box.setStyleSheet(
            f"background: {COLORS['panel']}; border-radius: 20px; "
            f"border: 1px solid {COLORS['border']};"
        )
        ib = QVBoxLayout(self.icon_box)
        ib.setContentsMargins(0, 0, 0, 0)
        self.icon = Icon(meta["icon"], size=22, color=meta["color"])
        ib.addWidget(self.icon, 0, Qt.AlignCenter)
        lay.addWidget(self.icon_box)

        # 타이틀 (서브타이틀 제거)
        self.title = QLabel(f"{meta['name']} 대시보드")
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

        self.dashboard = GogoPingDashboard(stream_client=self.stream_client)
        self.dashboard.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root_lay.addWidget(self.dashboard, 1)

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
            lambda state, sub: self.state_client.post_force_state(
                state, sub_task=sub,
                on_result=self.dashboard.debug_panel.set_last_result,
            )
        )

        # 긴급정지 버튼 → state_client.post_emergency_stop
        self.dashboard.debug_panel.emergency_stop_requested.connect(
            lambda: self.state_client.post_emergency_stop(
                on_result=self.dashboard.debug_panel.set_estop_result,
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

        # TopBar idle_timeout slider 적용 → state_client.post_idle_timeout
        self.topbar.set_idle_apply_callback(
            lambda seconds: self.state_client.post_idle_timeout(seconds)
        )

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
        super().closeEvent(ev)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Pingdergarten Admin")
    apply_theme(app)
    win = AdminWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
