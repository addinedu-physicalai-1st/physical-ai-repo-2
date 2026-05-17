"""CameraPanCard pytest-qt 단위 테스트.

키/버튼 hold → 10Hz 누적 publish, space=center, 클램프 검증.
pytest-qt 미설치 시 자동 skip.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pytestqt")
pytest.importorskip("PyQt5")

from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QKeyEvent

from widgets.camera_pan_card import (
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


def test_pan_right_key_accumulates_at_10hz(qtbot):
    card, calls = _make_card(qtbot)
    card.step_spin.setValue(2.0)
    card.setFocus()
    qtbot.waitUntil(card.hasFocus, timeout=1000)

    start_pan = card._target_pan
    _press(card, Qt.Key_D)
    qtbot.wait(550)  # 5 ticks worth
    _release(card, Qt.Key_D)
    qtbot.wait(150)

    # ~5 calls (즉시 1회 + 100ms 마다 4~5회 = 5~6) → 4~7 허용
    n = len(calls)
    assert 3 <= n <= 8, f"expected ~5 calls, got {n}"
    # 매 call 마다 pan 만 보낸다 (tilt 는 None)
    for pan, tilt in calls:
        assert tilt is None
        assert pan is not None
    # target_pan 누적
    assert card._target_pan > start_pan
    # 마지막 call 의 pan 이 현재 target 과 같다
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
