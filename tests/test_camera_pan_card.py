"""CameraPanCard pytest-qt 단위 테스트.

키/버튼 hold → 10Hz 누적 publish, space=center, 클램프 검증.
pytest-qt 미설치 시 자동 skip.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
pytest.importorskip("PyQt5")

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication, QLineEdit

from widgets.camera_pan_card import (
    CMD_TICK_MS,
    PAN_CENTER,
    PAN_MAX,
    PAN_MIN,
    TILT_CENTER,
    TILT_MAX,
    TILT_MIN,
    CameraPanCard,
)


def _make_card(qtbot):
    calls: list[tuple[float | None, float | None]] = []

    def _send(pan: float | None, tilt: float | None) -> bool:
        calls.append((pan, tilt))
        return True

    card = CameraPanCard(send_cmd=_send, get_health=lambda: None)
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)
    return card, calls


def _press(card, key: int) -> None:
    card.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, autorep=False))


def _release(card, key: int) -> None:
    card.keyReleaseEvent(QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier, autorep=False))


# ── focus / 기본 위젯 ─────────────────────────────────────────────────────


def test_focus_policy_strong(qtbot):
    card, _ = _make_card(qtbot)
    assert card.focusPolicy() == Qt.StrongFocus


def test_targets_start_at_center(qtbot):
    card, _ = _make_card(qtbot)
    assert card._target_pan == PAN_CENTER
    assert card._target_tilt == TILT_CENTER


# ── space → center ────────────────────────────────────────────────────────


def test_space_publishes_center(qtbot):
    card, calls = _make_card(qtbot)
    card._target_pan = 120.0
    card._target_tilt = 60.0
    card.setFocus()
    qtbot.waitUntil(card.hasFocus, timeout=1000)
    _press(card, Qt.Key_Space)
    assert (PAN_CENTER, TILT_CENTER) in calls
    assert card._target_pan == PAN_CENTER
    assert card._target_tilt == TILT_CENTER


# ── 키 hold → 10Hz 누적 publish ───────────────────────────────────────────


def test_pan_right_key_accumulates_at_tick_rate(qtbot):
    card, calls = _make_card(qtbot)
    card.step_spin.setValue(2.0)
    card.setFocus()
    qtbot.waitUntil(card.hasFocus, timeout=1000)

    start_pan = card._target_pan
    # 5 tick 정도 누름
    hold_ms = CMD_TICK_MS * 5 + CMD_TICK_MS // 2
    _press(card, Qt.Key_D)
    qtbot.wait(hold_ms)
    _release(card, Qt.Key_D)
    qtbot.wait(CMD_TICK_MS * 2)

    expected = hold_ms / CMD_TICK_MS  # ~5
    n = len(calls)
    # 즉시 1회 포함 + 타이밍 jitter → expected×0.5 ~ expected×1.8 허용
    assert expected * 0.5 <= n <= expected * 1.8 + 2, (
        f"expected ~{expected} calls, got {n} (tick={CMD_TICK_MS}ms)"
    )
    # 매 call 마다 pan 만 (tilt None)
    for pan, tilt in calls:
        assert tilt is None
        assert pan is not None
    assert card._target_pan > start_pan
    assert calls[-1][0] == card._target_pan


def test_arrow_keys_equivalent_to_wasd(qtbot):
    card, calls = _make_card(qtbot)
    card.step_spin.setValue(3.0)
    card.setFocus()
    qtbot.waitUntil(card.hasFocus, timeout=1000)

    _press(card, Qt.Key_Up)  # = W = tilt up
    qtbot.wait(250)
    _release(card, Qt.Key_Up)

    tilt_after = card._target_tilt
    assert tilt_after > TILT_CENTER
    # tilt 만 보낸 call 이 있어야 함
    assert any(p is None and t is not None for p, t in calls)


def test_diagonal_two_keys_publish_both_axes(qtbot):
    card, calls = _make_card(qtbot)
    card.step_spin.setValue(2.0)
    card.setFocus()
    qtbot.waitUntil(card.hasFocus, timeout=1000)

    _press(card, Qt.Key_D)  # right (pan +)
    _press(card, Qt.Key_W)  # up    (tilt +)
    qtbot.wait(250)
    _release(card, Qt.Key_D)
    _release(card, Qt.Key_W)

    assert card._target_pan > PAN_CENTER
    assert card._target_tilt > TILT_CENTER
    # 두 축 동시 보내는 call 이 최소 1번
    assert any(p is not None and t is not None for p, t in calls)


# ── 키 release 후 publish 멈춤 ────────────────────────────────────────────


def test_key_release_stops_publishing(qtbot):
    card, calls = _make_card(qtbot)
    card.setFocus()
    qtbot.waitUntil(card.hasFocus, timeout=1000)

    _press(card, Qt.Key_D)
    qtbot.wait(200)
    _release(card, Qt.Key_D)
    qtbot.wait(50)
    n_after_release = len(calls)
    qtbot.wait(400)
    # release 이후 새 call 없음 (잔여 1개 허용)
    assert len(calls) <= n_after_release + 1
    assert not card._publishing


# ── clamp ────────────────────────────────────────────────────────────────


def test_pan_clamped_to_max(qtbot):
    card, _ = _make_card(qtbot)
    card._target_pan = PAN_MAX - 1.0
    card.step_spin.setValue(20.0)
    card.setFocus()
    qtbot.waitUntil(card.hasFocus, timeout=1000)

    _press(card, Qt.Key_D)
    qtbot.wait(400)
    _release(card, Qt.Key_D)

    assert card._target_pan <= PAN_MAX


def test_tilt_clamped_to_min(qtbot):
    card, _ = _make_card(qtbot)
    card._target_tilt = TILT_MIN + 1.0
    card.step_spin.setValue(20.0)
    card.setFocus()
    qtbot.waitUntil(card.hasFocus, timeout=1000)

    _press(card, Qt.Key_S)  # tilt down
    qtbot.wait(400)
    _release(card, Qt.Key_S)

    assert card._target_tilt >= TILT_MIN


# ── on_state — WS payload ─────────────────────────────────────────────────


def test_on_state_updates_value_labels(qtbot):
    card, _ = _make_card(qtbot)
    card.on_state({"ros_ok": True, "pan_deg": 100.5, "tilt_deg": 70.2})
    assert "100.5" in card.pan_value.text()
    assert "70.2" in card.tilt_value.text()


def test_on_state_ros_off_badge(qtbot):
    card, _ = _make_card(qtbot)
    card.on_state({"ros_ok": False, "pan_deg": None, "tilt_deg": None})
    assert "off" in card.comm_badge.text().lower()


# ── 글로벌 단축키 (event filter) ──────────────────────────────────────────


def _send_app_key(key: int, press: bool = True) -> None:
    """QApplication 전체에 KeyPress/Release 이벤트 보냄.

    포커스 위젯에 sendEvent → app 의 eventFilter 가 가로채야 함.
    """
    ev_type = QEvent.KeyPress if press else QEvent.KeyRelease
    ev = QKeyEvent(ev_type, key, Qt.NoModifier, autorep=False)
    target = QApplication.focusWidget() or QApplication.instance()
    QApplication.sendEvent(target, ev)


def test_global_wasd_works_without_focus(qtbot):
    """WASD 글로벌 단축키: 카드에 포커스가 없어도 동작."""
    card, calls = _make_card(qtbot)
    # 카드 외 다른 위젯을 만들고 포커스 줌
    other = QLineEdit()
    qtbot.addWidget(other)
    other.show()
    qtbot.waitExposed(other)
    # text input 이면 가로채지 않으므로, 우선 카드도 다른 일반 위젯도 아닌 위젯에 포커스를 줌
    # → QLineEdit 자체엔 가로채면 안 됨 (다음 테스트). 여기서는 카드/입력위젯 둘 다 비활성화.
    card.clearFocus()
    other.clearFocus()
    assert QApplication.focusWidget() not in (card,)

    _send_app_key(Qt.Key_D, press=True)
    qtbot.wait(CMD_TICK_MS * 4)
    _send_app_key(Qt.Key_D, press=False)
    qtbot.wait(CMD_TICK_MS * 2)

    assert len(calls) >= 2, "global D 키가 publish 를 트리거해야 함"
    assert card._target_pan > PAN_CENTER


def test_global_c_centers(qtbot):
    """C 키 글로벌 = center 복귀."""
    card, calls = _make_card(qtbot)
    card._target_pan = 120.0
    card._target_tilt = 60.0
    card.clearFocus()
    _send_app_key(Qt.Key_C, press=True)
    qtbot.wait(20)
    assert (PAN_CENTER, TILT_CENTER) in calls
    assert card._target_pan == PAN_CENTER
    assert card._target_tilt == TILT_CENTER


def test_global_arrow_keys_NOT_intercepted(qtbot):
    """화살표는 글로벌 X — Teleop 과 충돌 방지. 카드 포커스 없으면 publish 안 됨."""
    card, calls = _make_card(qtbot)
    card.clearFocus()
    _send_app_key(Qt.Key_Right, press=True)
    qtbot.wait(CMD_TICK_MS * 3)
    _send_app_key(Qt.Key_Right, press=False)
    assert len(calls) == 0, f"화살표는 글로벌이면 안 됨, got {len(calls)}"


def test_global_wasd_ignored_in_text_input(qtbot):
    """QLineEdit 안에서 'd' 타이핑 시 카메라 동작 안 함 (타이핑 보존)."""
    card, calls = _make_card(qtbot)
    le = QLineEdit()
    qtbot.addWidget(le)
    le.show()
    qtbot.waitExposed(le)
    le.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is le, timeout=1000)

    qtbot.keyClick(le, Qt.Key_D)
    qtbot.wait(CMD_TICK_MS * 2)
    assert len(calls) == 0, "text input 안에서는 WASD 가 카메라로 가지 않아야 함"
    assert "d" in le.text().lower()
