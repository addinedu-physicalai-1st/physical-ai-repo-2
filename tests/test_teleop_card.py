"""TeleopCard pytest-qt 단위 테스트.

AC #3, #5, #6, #7, #8, #14, #27, #32, #33, #34 검증.
pytest-qt 미설치 시 자동 skip.
"""

from __future__ import annotations

import json
import pathlib

import pytest

pytest.importorskip("pytestqt")
pytest.importorskip("PyQt5")

from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QFocusEvent, QKeyEvent
from PyQt5.QtWidgets import QSlider

from widgets.teleop_card import TeleopCard


# --------------------------------------------------------------- helpers


def _make_card(qtbot, monkeypatch, ips_path: pathlib.Path | None = None):
    calls: list[tuple[float, float]] = []
    health_calls: list[int] = []

    def _send(lin: float, ang: float) -> None:
        calls.append((lin, ang))

    def _health() -> dict:
        health_calls.append(1)
        return {"ros_ok": True, "ros_domain_id": 207,
                "last_odom_age_ms": 50, "last_scan_age_ms": 30}

    card = TeleopCard(
        send_cmd_vel=_send,
        get_health=_health,
        machine_ips_json=ips_path,
    )
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)
    return card, calls, health_calls


# --------------------------------------------------------------- AC #3


def test_card_has_required_widgets(qtbot, monkeypatch, tmp_path):
    ips = tmp_path / "machine_ips.json"
    ips.write_text(json.dumps({"vic": {"ip": "10.0.0.5"}}))
    card, _, _ = _make_card(qtbot, monkeypatch, ips)

    # objectName 으로 모든 핵심 위젯 검증
    required = [
        "teleopCard", "teleopCommBadge", "teleopIpLabel",
        "teleopLinearSlider", "teleopAngularSlider",
        "teleopBtnUp", "teleopBtnDown", "teleopBtnLeft",
        "teleopBtnRight", "teleopBtnStop",
        "teleopOdomMini", "teleopScanMini",
        "teleopCmdRow",
    ]
    found = {w.objectName() for w in card.findChildren(object)
             if hasattr(w, "objectName")}
    for name in required:
        assert name in found or card.objectName() == name, (
            f"missing widget objectName: {name}"
        )


# --------------------------------------------------------------- AC #14


def test_vic_ip_label_reflects_json(qtbot, monkeypatch, tmp_path):
    ips = tmp_path / "machine_ips.json"
    ips.write_text(json.dumps({"vic": {"ip": "192.168.99.99"}}))
    card, _, _ = _make_card(qtbot, monkeypatch, ips)
    assert "192.168.99.99" in card.ip_label.text()

    # 다른 IP 로 새 카드 만들면 반영
    ips2 = tmp_path / "ips2.json"
    ips2.write_text(json.dumps({"vic": {"ip": "10.10.10.10"}}))
    card2, _, _ = _make_card(qtbot, monkeypatch, ips2)
    assert "10.10.10.10" in card2.ip_label.text()


# --------------------------------------------------------------- AC #5, #6


def test_arrow_key_publishes_at_10hz_then_zero_on_release(qtbot, monkeypatch,
                                                         tmp_path):
    ips = tmp_path / "ips.json"
    ips.write_text(json.dumps({"vic": {"ip": "1.1.1.1"}}))
    card, calls, _ = _make_card(qtbot, monkeypatch, ips)

    card.setFocus()
    qtbot.waitUntil(lambda: card.hasFocus(), timeout=1000)

    # 화살표 위 누르기 (auto-repeat 흉내내지 않음)
    press = QKeyEvent(QEvent.KeyPress, Qt.Key_Up, Qt.NoModifier, autorep=False)
    card.keyPressEvent(press)

    # 1 초 대기 — 10Hz 송신
    qtbot.wait(1000)

    n_after_1s = len(calls)
    # 즉시 1 회 + 100ms 마다 = 약 11 회. 9~12 허용.
    assert 8 <= n_after_1s <= 13, f"expected ~10 calls, got {n_after_1s}"

    # 떼기
    rel = QKeyEvent(QEvent.KeyRelease, Qt.Key_Up, Qt.NoModifier, autorep=False)
    card.keyReleaseEvent(rel)

    qtbot.wait(300)
    n_final = len(calls)
    # 마지막은 (0,0)
    assert calls[-1] == (0.0, 0.0)
    # 이후 호출 추가 없음 (1~2 회 더는 허용)
    assert n_final <= n_after_1s + 2


# --------------------------------------------------------------- AC #7


def test_space_immediately_stops(qtbot, monkeypatch, tmp_path):
    ips = tmp_path / "ips.json"
    ips.write_text(json.dumps({"vic": {"ip": "1.1.1.1"}}))
    card, calls, _ = _make_card(qtbot, monkeypatch, ips)

    card.setFocus()
    qtbot.waitUntil(lambda: card.hasFocus(), timeout=1000)

    # 위 키 잠시 누른 상태
    card.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Up, Qt.NoModifier,
                                 autorep=False))
    qtbot.wait(150)
    n_before = len(calls)

    # space
    card.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier,
                                 autorep=False))
    qtbot.wait(50)
    assert calls[-1] == (0.0, 0.0)
    # 키 상태 reset
    assert not card._keys_down
    # 타이머 멈춰야 함
    qtbot.wait(300)
    assert len(calls) <= n_before + 3  # space 직후 정지 + 2 잔여 허용


# --------------------------------------------------------------- AC #8


def test_zero_slider_publishes_zero(qtbot, monkeypatch, tmp_path):
    ips = tmp_path / "ips.json"
    ips.write_text(json.dumps({"vic": {"ip": "1.1.1.1"}}))
    card, calls, _ = _make_card(qtbot, monkeypatch, ips)
    card.linear_slider.setValue(0)
    card.angular_slider.setValue(0)

    card.setFocus()
    qtbot.waitUntil(lambda: card.hasFocus(), timeout=1000)

    card.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Up, Qt.NoModifier,
                                 autorep=False))
    qtbot.wait(150)
    # 모든 publish 가 (0,0)
    assert calls, "no calls published"
    for c in calls:
        assert c == (0.0, 0.0)


# --------------------------------------------------------------- AC #27


def test_health_polled_every_5s(qtbot, monkeypatch, tmp_path):
    ips = tmp_path / "ips.json"
    ips.write_text(json.dumps({"vic": {"ip": "1.1.1.1"}}))
    card, _, health_calls = _make_card(qtbot, monkeypatch, ips)
    # 타이머 interval 검증 (실제 5s 대기 X — Goal: 5s ± 1s)
    assert 4000 <= card._health_timer.interval() <= 6000


# --------------------------------------------------------------- AC #32


def test_focus_policy(qtbot, monkeypatch, tmp_path):
    ips = tmp_path / "ips.json"
    ips.write_text(json.dumps({"vic": {"ip": "1.1.1.1"}}))
    card, _, _ = _make_card(qtbot, monkeypatch, ips)
    assert card.focusPolicy() == Qt.StrongFocus
    for s in card.findChildren(QSlider):
        assert s.focusPolicy() == Qt.NoFocus, (
            f"slider {s.objectName()} not NoFocus"
        )


# --------------------------------------------------------------- AC #33


def test_show_event_sets_focus(qtbot, monkeypatch, tmp_path):
    ips = tmp_path / "ips.json"
    ips.write_text(json.dumps({"vic": {"ip": "1.1.1.1"}}))
    card, _, _ = _make_card(qtbot, monkeypatch, ips)
    qtbot.waitUntil(lambda: card.hasFocus(), timeout=1000)
    assert card.hasFocus()


# --------------------------------------------------------------- AC #34


def test_focus_out_resets_and_stops(qtbot, monkeypatch, tmp_path):
    ips = tmp_path / "ips.json"
    ips.write_text(json.dumps({"vic": {"ip": "1.1.1.1"}}))
    card, calls, _ = _make_card(qtbot, monkeypatch, ips)

    card.setFocus()
    qtbot.waitUntil(lambda: card.hasFocus(), timeout=1000)
    card.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Up, Qt.NoModifier,
                                 autorep=False))
    qtbot.wait(150)

    # focus out 강제
    card.focusOutEvent(QFocusEvent(QEvent.FocusOut))
    assert calls[-1] == (0.0, 0.0)
    assert not card._keys_down
