"""TopBar inline BT 상태 3칸 위젯 — GogoPing 페이지 전용.

[state] [BT main] [BT sub] 세 칸이 가로로 배치되어 TopBar 의 타이틀 우측에 들어간다.

- 셀 1 (state): FSM state 알약. 색상은 state 별 (CHARGING=하늘, IDLE=회색,
                task states (GOTO/FOLLOW/LULLABY)=각자 다른 파스텔, HIDEANDSEEK=라벤더, RETURNING=주황, ERROR=빨강).
- 셀 2 (BT main): tree 이름 + 모든 children 을 status 별로 시각 차별:
                  ● (sky, bold)   = RUNNING — 현재 실행 중
                  ✓ (muted)       = SUCCESS — 완료, 취소선
                  ✗ (red, bold)   = FAILURE
                  ○ (faint)       = INVALID / PENDING — 아직 실행 안 됨
                  Sequence 의 진행도가 한눈에 보임.
- 셀 3 (BT sub):  동일 포맷. SubTree 없으면 "—" placeholder.

EduPing/NoriArm 페이지에서는 hide() 로 숨김 — gogoping 페이지에서만 노출.

snapshot 포맷:
  {
    "robot_id": "gogoping",
    "fsm_state": "GOTO",
    "main_tree": {
      "name": "MainTree[GOTO]",
      "children": [
        {"name": "BatteryLowMonitor",     "status": "RUNNING"},
        {"name": "HardwareHealthMonitor", "status": "RUNNING"},
        ...
      ]
    },
    "sub_tree": {
      "name": "BT_return_sub",
      "children": [
        {"name": "NavigateToPose",  "status": "SUCCESS"},
        {"name": "AlignToDock",     "status": "RUNNING"},
        {"name": "ApproachDock",    "status": "INVALID"},
        {"name": "VerifyDocking",   "status": "INVALID"},
      ]
    } | None
  }

호환: 기존 "running_children": [str] 포맷도 받음 — 모두 RUNNING 으로 간주.

API:
  update_snapshot(snapshot: dict) — state_client () 가 호출
  reset() — 모든 셀을 placeholder 로
  show() / hide() — 페이지 전환 시 TopBar 가 호출
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from theme import COLORS

from . import soften


# FSM state → (강조 색, 텍스트 색) 매핑.
_STATE_COLORS: dict[str, tuple[str, str]] = {
    "IDLE":                (COLORS["text_muted"],     COLORS["text"]),
    "CHARGING":            (COLORS["sky"],            COLORS["text"]),
    # 평탄화 (2026-05-25): 4 task state 각자 고유 색.
    "GOTO":                (COLORS["mint"],           COLORS["text"]),
    "FOLLOW":              (COLORS["sky"],            COLORS["text"]),
    "LULLABY":             (COLORS["sun"],            COLORS["text"]),
    "HIDEANDSEEK":         (COLORS["lavender"],       COLORS["text"]),
    "MANUAL":              (COLORS["primary_dim"],    COLORS["text"]),     # 분홍 — 사용자 직접 제어
    "RETURNING":           (COLORS["accent"],         COLORS["text"]),     # 주황 — 자발 복귀
    "LOW_BATTERY_RETURNING":  (COLORS["warning"],        COLORS["text"]),     # 진한 주황 — lockdown
    "ERROR":               (COLORS["danger"],         COLORS["danger"]),
    "—":                   (COLORS["border_strong"],  COLORS["text_muted"]),
}

_PLACEHOLDER = "—"


def _render_child_html(child: dict) -> str:
    """status 별 시각화 — 점/체크/엑스 + 텍스트 스타일.

    ``child["disabled"] == True`` 면 status 와 무관하게 *비활성* 표시 (회색 ⊘ +
    strikethrough + dim 텍스트). 시연/디버그용 monitor disable 시 표시. snapshot 의
    ``disabled`` 키는 tree_inspector._leaf_dict 가 monitor 의 ``_disabled`` 속성
    True 일 때만 포함.
    """
    name = str(child.get("name", "?"))
    status = str(child.get("status", "INVALID")).upper()

    if child.get("disabled"):
        return (
            f"<span style='color: {COLORS['text_muted']};'>⊘</span>"
            f"&nbsp;<span style='color: {COLORS['text_muted']}; "
            f"text-decoration: line-through;'>{name}</span>"
            f"&nbsp;<span style='color: {COLORS['warning']}; font-size: 8pt;'>(disabled)</span>"
        )

    if status == "RUNNING":
        # 강조 — 가장 눈에 띄게
        return (
            f"<span style='color: {COLORS['sky']};'>●</span>"
            f"&nbsp;<b style='color: {COLORS['text']};'>{name}</b>"
        )
    if status == "SUCCESS":
        # 완료 — 옅은 회색 + 취소선
        return (
            f"<span style='color: {COLORS['success']};'>✓</span>"
            f"&nbsp;<span style='color: {COLORS['text_muted']}; "
            f"text-decoration: line-through;'>{name}</span>"
        )
    if status == "FAILURE":
        # 실패 — 빨강 + bold
        return (
            f"<span style='color: {COLORS['danger']};'>✗</span>"
            f"&nbsp;<b style='color: {COLORS['danger']};'>{name}</b>"
        )
    # INVALID / PENDING / 그 외 — 옅은 회색 점
    return (
        f"<span style='color: {COLORS['border_strong']};'>○</span>"
        f"&nbsp;<span style='color: {COLORS['text_muted']};'>{name}</span>"
    )


def _normalize_children(tree_block: dict) -> list[dict]:
    """새 포맷 (children) 우선, 없으면 옛 포맷 (running_children) 을 흡수."""
    children = tree_block.get("children")
    if children is not None:
        return list(children)
    legacy = tree_block.get("running_children") or []
    return [{"name": n, "status": "RUNNING"} for n in legacy]


# --------------------------------------------------------------------------
# 내부 셀
# --------------------------------------------------------------------------


class _Cell(QFrame):
    """3칸 공용 베이스 — 둥근 카드 1개 + 헤더(작은 라벨) + 본문 QVBoxLayout."""

    def __init__(self, header: str, parent=None):
        super().__init__(parent)
        self.setObjectName("btCell")
        self.setStyleSheet(
            f"""
            QFrame#btCell {{
                background: {COLORS['panel']};
                border: 1px solid {COLORS['border']};
                border-radius: 10px;
            }}
            QFrame#btCell QLabel {{ background: transparent; }}
            """
        )
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 5, 10, 6)
        outer.setSpacing(2)

        head = QLabel(header)
        head.setStyleSheet(
            f"font-size: 8pt; font-weight: 800; color: {COLORS['text_muted']}; "
            f"letter-spacing: 0.8px; text-transform: uppercase;"
        )
        outer.addWidget(head)

        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(1)
        outer.addLayout(self._body)


class _StateCell(_Cell):
    """state 칸 — FSM state 알약 1개."""

    def __init__(self, parent=None):
        super().__init__("state", parent)
        self.setMinimumWidth(96)

        self._badge = QLabel(_PLACEHOLDER)
        self._badge.setAlignment(Qt.AlignCenter)
        self._badge.setMinimumHeight(26)
        self._body.addWidget(self._badge)

        self.set_state(_PLACEHOLDER)

    def set_state(self, state: str) -> None:
        accent, text_color = _STATE_COLORS.get(state, _STATE_COLORS[_PLACEHOLDER])
        bg = soften(accent, 0.22)
        self._badge.setText(state)
        self._badge.setStyleSheet(
            f"""
            QLabel {{
                background: {bg};
                color: {text_color};
                border: 1px solid {soften(accent, 0.55)};
                border-radius: 13px;
                padding: 2px 12px;
                font-size: 11pt;
                font-weight: 800;
                letter-spacing: 0.5px;
            }}
            """
        )


class _TreeCell(_Cell):
    """BT main / BT sub 칸 — tree 이름 + 모든 children 을 status 별로 시각화."""

    def __init__(self, header: str, kind: str, parent=None):
        super().__init__(header, parent)
        self._kind = kind  # "main" / "sub" — placeholder 안내문에 사용
        self.setMinimumWidth(208)
        self.setMaximumWidth(300)

        self._title = QLabel(_PLACEHOLDER)
        self._title.setStyleSheet(
            f"font-size: 10pt; font-weight: 800; color: {COLORS['text']};"
        )
        self._body.addWidget(self._title)

        # children 은 <br> 로 줄바꿈된 단일 QLabel — 자식 수가 많으면 (patrol 처럼 13+
        # vertex) 셀이 페이지를 벗어남. QScrollArea 로 감싸 max height 까지만 보이고
        # 그 이상은 wheel 로 셀 내부 스크롤.
        self._children = QLabel("")
        self._children.setTextFormat(Qt.RichText)
        self._children.setWordWrap(False)
        self._children.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._children.setStyleSheet(
            f"font-size: 9pt; color: {COLORS['text_soft']}; line-height: 1.35;"
        )

        self._children_scroll = QScrollArea()
        self._children_scroll.setWidget(self._children)
        self._children_scroll.setWidgetResizable(True)
        self._children_scroll.setFrameShape(QScrollArea.NoFrame)
        self._children_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._children_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # cell 의 자식 영역 max height — patrol 같은 긴 리스트는 이 안에서 스크롤.
        # 13~14 줄 정도 보임 (9pt × line-height 1.35 ≈ 16px/line, 220/16 ≈ 13).
        self._children_scroll.setMaximumHeight(220)
        self._children_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self._body.addWidget(self._children_scroll)

        self.set_data(None)

    def set_data(self, tree_block: dict | None) -> None:
        if tree_block is None:
            self._title.setText(_PLACEHOLDER)
            self._children.setText(
                f"<span style='color: {COLORS['text_muted']};'>"
                f"({self._kind} BT 없음)</span>"
            )
            return
        self._title.setText(tree_block.get("name", _PLACEHOLDER))
        children = _normalize_children(tree_block)
        if not children:
            self._children.setText(
                f"<span style='color: {COLORS['text_muted']};'>"
                f"(자식 없음)</span>"
            )
            return
        lines = [_render_child_html(c) for c in children]
        self._children.setText("<br>".join(lines))


# --------------------------------------------------------------------------
# 외부 노출 위젯
# --------------------------------------------------------------------------


class BTStateInline(QWidget):
    """TopBar 우측에 들어가는 inline 3칸 BT 상태 위젯.

    AdminWindow 가 페이지 전환 시 show()/hide() 로 노출 제어.
    추후 의 state_client 가 update_snapshot() 으로 갱신.

    snapshot 포맷:
      {
        "robot_id": "gogoping",
        "fsm_state": "GOTO",
        "main_tree": {"name": "BT_goto_main", "running_children": [...]},
        "sub_tree":  None,
      }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._state = _StateCell()
        self._main = _TreeCell("BT main", kind="main")
        self._sub = _TreeCell("BT sub", kind="sub")

        # 디버그 패널 (DebugStatePanel / BatteryDebugSlider / PoseDebugPanel) 은
        # GogoPingDashboard 의 우측 DebugDrawer 로 분리됨. BTStateInline 은 BT 상태
        # 셀 3개 (state/main/sub) 만 유지.
        lay.addWidget(self._state, 0, Qt.AlignVCenter)
        lay.addWidget(self._main, 0, Qt.AlignVCenter)
        lay.addWidget(self._sub, 0, Qt.AlignVCenter)

    # ------------------------------------------------------------------ API

    def update_snapshot(self, snapshot: dict) -> None:
        """state_client 가 WS 메시지 받아서 호출."""
        self._state.set_state(snapshot.get("fsm_state", _PLACEHOLDER))
        self._main.set_data(snapshot.get("main_tree"))
        self._sub.set_data(snapshot.get("sub_tree"))

    def reset(self) -> None:
        """모든 셀을 placeholder 로 되돌림 — 페이지 전환 시 호출 권장."""
        self._state.set_state(_PLACEHOLDER)
        self._main.set_data(None)
        self._sub.set_data(None)
