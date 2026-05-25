"""디버그 강제 state 전이 컴팩트 카드 — BT SUB 셀 옆.

평탄화 (2026-05-25): sub_task combo 제거. state combo + "적용" 버튼만.
10 state 중 하나 선택 후 적용 → ForceState.srv 호출.

BT SUB 셀과 같은 카드 스타일로 BTStateInline 의 가로 row 에 자연스럽게 들어감.

사용:
    panel = DebugStatePanel()
    panel.force_state_requested.connect(
        lambda state: state_client.post_force_state(state, on_result=panel.set_last_result)
    )
"""
from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from theme import COLORS

from . import soften

_STATES = (
    "IDLE", "CHARGING", "GOTO", "FOLLOW", "LULLABY", "HIDEANDSEEK",
    "MANUAL", "RETURNING", "LOW_BATTERY_RETURNING", "ERROR",
)


class DebugStatePanel(QFrame):
    """state 콤보 + 적용 버튼."""

    # 적용 버튼 클릭 시 emit. 인자: (target_state,)
    force_state_requested = pyqtSignal(str)
    # 긴급정지 버튼 클릭 시 emit. 인자 없음.
    emergency_stop_requested = pyqtSignal()
    # [순찰] 빠른 버튼 클릭 시 emit. 인자 없음 — control-server 가 랜덤 그룹 선택.
    patrol_requested = pyqtSignal()
    # 숨바꼭질 [→ skip phase] 버튼 클릭 시 emit. 인자: (current_phase,)
    hideseek_skip_phase_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("debugStatePanel")
        # BT SUB 셀과 같은 카드 스타일 — 단 디버그 표시로 노란 border
        self.setStyleSheet(
            f"""
            QFrame#debugStatePanel {{
                background: {soften(COLORS['warning'], 0.30)};
                border: 1px dashed {soften(COLORS['warning'], 0.60)};
                border-radius: 10px;
            }}
            QFrame#debugStatePanel QLabel {{ background: transparent; }}
            QComboBox {{
                background: {COLORS['panel']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 2px 6px;
                font-size: 9pt;
                font-weight: 700;
                color: {COLORS['text']};
                min-height: 22px;
            }}
            QPushButton {{
                background: {COLORS['warning']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 9pt;
                font-weight: 800;
                min-height: 24px;
            }}
            QPushButton:hover {{
                background: {soften(COLORS['warning'], 0.80)};
            }}
            QPushButton:pressed {{
                background: {soften(COLORS['warning'], 0.50)};
            }}
            """
        )
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.setMinimumWidth(208)
        self.setMaximumWidth(280)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 5, 10, 6)
        outer.setSpacing(3)

        # 헤더
        header = QLabel("🔧 DEBUG")
        header.setStyleSheet(
            f"font-size: 8pt; font-weight: 800; color: {COLORS['text_muted']}; "
            f"letter-spacing: 0.8px;"
        )
        outer.addWidget(header)

        # 긴급정지 — 별도 큰 빨간 버튼. 한 번 누르면 ERROR (terminal) 진입.
        # std_srvs/Trigger 호출 → command_listener._on_emergency_stop_request →
        # fsm.force_state("ERROR") → BT_error_main 의 StopAllMotors (cmd_vel=0 + torque OFF).
        self._estop_btn = QPushButton("🛑 긴급정지")
        self._estop_btn.setCursor(Qt.PointingHandCursor)
        self._estop_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {COLORS['danger']}; color: white; border: none;"
            f"  border-radius: 8px; padding: 8px 12px; font-size: 11pt; font-weight: 900;"
            f"  min-height: 34px;"
            f"}}"
            f"QPushButton:hover {{ background: {soften(COLORS['danger'], 0.80)}; }}"
            f"QPushButton:pressed {{ background: {soften(COLORS['danger'], 0.50)}; }}"
        )
        self._estop_btn.clicked.connect(self._on_estop_clicked)
        outer.addWidget(self._estop_btn)

        # 빠른 토글: [수동] [주행] — combo 거치지 않고 즉시 force-state.
        # state row 아래 일반 흐름은 그대로 유지 (정밀 선택용).
        quick_row = QHBoxLayout()
        quick_row.setSpacing(4)
        quick_row.setContentsMargins(0, 0, 0, 0)
        quick_label = QLabel("quick")
        quick_label.setStyleSheet(
            f"font-size: 8pt; color: {COLORS['text_soft']}; min-width: 28px;"
        )
        quick_row.addWidget(quick_label)
        self._quick_manual_btn = QPushButton("수동")
        self._quick_manual_btn.setCursor(Qt.PointingHandCursor)
        self._quick_manual_btn.setStyleSheet(
            f"background: {COLORS['primary']}; color: white; border: none;"
            f" border-radius: 6px; padding: 4px 10px; font-size: 9pt; font-weight: 800;"
            f" min-height: 24px;"
        )
        self._quick_manual_btn.clicked.connect(lambda: self._quick_apply("MANUAL"))
        quick_row.addWidget(self._quick_manual_btn, 1)
        self._quick_drive_btn = QPushButton("주행")
        self._quick_drive_btn.setCursor(Qt.PointingHandCursor)
        self._quick_drive_btn.setStyleSheet(
            f"background: {COLORS['mint']}; color: {COLORS['text']}; border: none;"
            f" border-radius: 6px; padding: 4px 10px; font-size: 9pt; font-weight: 800;"
            f" min-height: 24px;"
        )
        self._quick_drive_btn.clicked.connect(lambda: self._quick_apply("IDLE"))
        quick_row.addWidget(self._quick_drive_btn, 1)
        # [순찰] — control-server 가 random 그룹 선택 → SetGoal(HIDEANDSEEK) 발사
        self._quick_patrol_btn = QPushButton("순찰")
        self._quick_patrol_btn.setCursor(Qt.PointingHandCursor)
        self._quick_patrol_btn.setStyleSheet(
            f"background: {COLORS['warning']}; color: white; border: none;"
            f" border-radius: 6px; padding: 4px 10px; font-size: 9pt; font-weight: 800;"
            f" min-height: 24px;"
        )
        self._quick_patrol_btn.clicked.connect(self._on_patrol_clicked)
        quick_row.addWidget(self._quick_patrol_btn, 1)
        outer.addLayout(quick_row)

        # 숨바꼭질 debug skip — 현재 phase 표시 + skip 버튼.
        # snapshot 의 hideseek_phase 가 recruit/countdown/patrol/return 일 때만 enable.
        self._hideseek_phase: str = ""
        hideseek_row = QHBoxLayout()
        hideseek_row.setSpacing(4)
        hideseek_row.setContentsMargins(0, 0, 0, 0)
        hideseek_label = QLabel("hideseek")
        hideseek_label.setStyleSheet(
            f"font-size: 8pt; color: {COLORS['text_soft']}; min-width: 48px;"
        )
        hideseek_row.addWidget(hideseek_label)
        self._hideseek_phase_label = QLabel("—")
        self._hideseek_phase_label.setStyleSheet(
            f"font-size: 9pt; font-weight: 700; color: {COLORS['text']};"
            f" min-width: 80px;"
        )
        hideseek_row.addWidget(self._hideseek_phase_label, 1)
        self._hideseek_skip_btn = QPushButton("→ 다음")
        self._hideseek_skip_btn.setCursor(Qt.PointingHandCursor)
        self._hideseek_skip_btn.setStyleSheet(
            f"background: {COLORS['warning']}; color: white; border: none;"
            f" border-radius: 6px; padding: 4px 10px; font-size: 9pt; font-weight: 800;"
            f" min-height: 24px;"
        )
        self._hideseek_skip_btn.clicked.connect(self._on_hideseek_skip_clicked)
        self._hideseek_skip_btn.setEnabled(False)
        hideseek_row.addWidget(self._hideseek_skip_btn, 0)
        outer.addLayout(hideseek_row)

        # state row
        state_row = QHBoxLayout()
        state_row.setSpacing(4)
        state_row.setContentsMargins(0, 0, 0, 0)
        state_label = QLabel("state")
        state_label.setStyleSheet(
            f"font-size: 8pt; color: {COLORS['text_soft']}; min-width: 28px;"
        )
        state_row.addWidget(state_label)
        self._state_combo = QComboBox()
        self._state_combo.addItems(list(_STATES))
        state_row.addWidget(self._state_combo, 1)
        # 적용 버튼 — state row 옆에 배치
        self._apply_btn = QPushButton("적용")
        self._apply_btn.setCursor(Qt.PointingHandCursor)
        self._apply_btn.clicked.connect(self._on_apply)
        state_row.addWidget(self._apply_btn, 0)
        outer.addLayout(state_row)

        # 마지막 결과 표시 (한 줄)
        self._last_result = QLabel("")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {COLORS['text_soft']};"
        )
        outer.addWidget(self._last_result)

    # --------------------------------------------------------------- internal

    def _on_apply(self) -> None:
        state = self._state_combo.currentText()
        self._last_result.setText(f"sending → {state} ...")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {COLORS['text_soft']};"
        )
        self.force_state_requested.emit(state)

    def _quick_apply(self, state: str) -> None:
        """수동/주행 빠른 토글 — 즉시 force-state. combo 동기화 안 함."""
        self._last_result.setText(f"sending → {state} (quick) ...")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {COLORS['text_soft']};"
        )
        self.force_state_requested.emit(state)

    def _on_estop_clicked(self) -> None:
        """긴급정지 버튼 — 확인 없이 즉시 발사 (안전 우선)."""
        self._last_result.setText("sending → EMERGENCY STOP ...")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 700; color: {COLORS['danger']};"
        )
        self.emergency_stop_requested.emit()

    def _on_patrol_clicked(self) -> None:
        """[순찰] — 즉시 랜덤 그룹 발사. control-server 가 group 선택."""
        self._last_result.setText("sending → 순찰 (랜덤 그룹) ...")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {COLORS['text_soft']};"
        )
        self.patrol_requested.emit()

    def _on_hideseek_skip_clicked(self) -> None:
        """숨바꼭질 [→ 다음] — 현재 phase 를 BT 측에서 즉시 SUCCESS."""
        phase = self._hideseek_phase
        if not phase:
            return
        self._last_result.setText(f"sending → hideseek skip ({phase}) ...")
        self._last_result.setStyleSheet(
            f"font-size: 8pt; font-weight: 600; color: {COLORS['text_soft']};"
        )
        self.hideseek_skip_phase_requested.emit(phase)

    # --------------------------------------------------------------- public

    def set_last_result(self, state: str, ok: bool, reason: str = "") -> None:
        """state_client 가 POST 응답 받은 후 호출."""
        if ok:
            self._last_result.setText(f"✓ {state}")
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {COLORS['success']};"
            )
        else:
            self._last_result.setText(f"✗ {state}: {reason}")
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {COLORS['danger']};"
            )

    _SKIPPABLE_PHASES = frozenset({
        "recruit", "countdown", "patrol", "return",
    })
    _PHASE_LABELS = {
        "": "—",
        "move_to_play": "이동 중",
        "recruit": "모집",
        "countdown": "카운트다운",
        "patrol": "순찰",
        "return": "복귀",
        "end": "발표",
    }

    def set_hideseek_phase(self, phase: str) -> None:
        """snapshot 의 hideseek_phase 가 변경될 때 호출 — 라벨 + skip 버튼 enable 상태 갱신."""
        self._hideseek_phase = phase or ""
        label = self._PHASE_LABELS.get(self._hideseek_phase, self._hideseek_phase or "—")
        self._hideseek_phase_label.setText(label)
        self._hideseek_skip_btn.setEnabled(
            self._hideseek_phase in self._SKIPPABLE_PHASES,
        )

    def set_hideseek_skip_result(
        self, current_phase: str, ok: bool, reason: str = "",
        advanced_to: str = "",
    ) -> None:
        """state_client 가 hideseek skip-phase 응답 받은 후 호출."""
        if ok:
            target = self._PHASE_LABELS.get(advanced_to, advanced_to or "?")
            self._last_result.setText(
                f"✓ hideseek skip {current_phase} → {target}"
            )
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {COLORS['success']};"
            )
        else:
            self._last_result.setText(f"✗ hideseek skip ({current_phase}): {reason}")
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {COLORS['danger']};"
            )

    def set_patrol_result(
        self, ok: bool, reason: str = "",
        group_order: list[str] | None = None,
        vertices: list[str] | None = None,
    ) -> None:
        """state_client 가 /debug/patrol 응답 받은 후 호출."""
        if ok:
            n = len(vertices) if vertices else 0
            grps = " → ".join(group_order) if group_order else "?"
            self._last_result.setText(f"✓ 순찰 {grps} ({n} vertex)")
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {COLORS['success']};"
            )
        else:
            self._last_result.setText(f"✗ 순찰: {reason}")
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {COLORS['danger']};"
            )

    def set_estop_result(self, ok: bool, reason: str = "") -> None:
        """state_client 가 emergency_stop POST 응답 받은 후 호출."""
        if ok:
            self._last_result.setText("✓ EMERGENCY STOP — ERROR state")
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 800; color: {COLORS['danger']};"
            )
        else:
            self._last_result.setText(f"✗ EMERGENCY STOP: {reason}")
            self._last_result.setStyleSheet(
                f"font-size: 8pt; font-weight: 700; color: {COLORS['danger']};"
            )
