"""WaypointMapCard 편집 모드 + 상태머신 + hover + endpoint 호출 검증."""
from __future__ import annotations

import pytest
from pathlib import Path

pytest.importorskip("pytestqt")
pytest.importorskip("PyQt5")


@pytest.fixture
def card(qtbot, tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ui/admin-ui"))
    svg = tmp_path / "admin_map.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 881 720" '
        'width="881" height="720"></svg>',
        encoding="utf-8",
    )
    monkeypatch.setenv("PINGDER_ADMIN_MAP_SVG", str(svg))
    from widgets.waypoint_map_card import WaypointMapCard
    c = WaypointMapCard()
    qtbot.addWidget(c)
    return c


# ---- Task 19: 편집 모드 토글 ----
def test_edit_mode_initially_off(card):
    assert card._map._edit_mode is False
    assert card._map._edit_state == "ready"


def test_edit_mode_toggle_on_when_nav_idle(card, monkeypatch):
    import httpx
    class StubResp:
        status_code = 200
        def json(self): return {"nav_active": False}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: StubResp())

    card._btn_edit.setChecked(True)
    card._on_edit_toggle()
    assert card._map._edit_mode is True


def test_edit_mode_refuses_when_nav_active(card, monkeypatch):
    import httpx
    class StubResp:
        status_code = 200
        def json(self): return {"nav_active": True}
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: StubResp())
    # QMessageBox 우회
    from PyQt5.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **kw: None))

    card._btn_edit.setChecked(True)
    card._on_edit_toggle()
    assert card._map._edit_mode is False
    assert card._btn_edit.isChecked() is False


def test_edit_mode_off_resets_state(card, monkeypatch):
    card._map._edit_mode = True
    card._map._edit_state = "link_pending"
    card._map._selected_node = "A"
    card._btn_edit.setChecked(False)
    card._on_edit_toggle()
    assert card._map._edit_mode is False
    assert card._map._edit_state == "ready"
    assert card._map._selected_node is None


# ---- Task 20: hit_test (node + lane) ----
def test_hit_test_node(card):
    from PyQt5.QtCore import QPointF
    card._map.set_waypoints([{"name": "A", "x": 0.0, "y": 0.0}])
    p = card._map._map_to_widget(0.0, 0.0)
    target = card._map._hit_test(p)
    assert target is not None
    assert target["kind"] == "node"
    assert target["id"] == "A"


def test_hit_test_lane_midpoint(card):
    from PyQt5.QtCore import QPointF
    # widget size 가 작아 노드 간격이 너무 좁으면 midpoint 가 양쪽 노드 hit 반경 안
    # 들어와 lane 보다 node 가 잡힌다. 5m 떨어뜨려 안전 마진 확보.
    card._map.set_waypoints([
        {"name": "A", "x": 0.0, "y": 0.0},
        {"name": "B", "x": 5.0, "y": 0.0},
    ])
    card._map.set_lanes([{"from": "A", "to": "B", "bidirectional": True}])
    pa = card._map._map_to_widget(0.0, 0.0)
    pb = card._map._map_to_widget(5.0, 0.0)
    mid = QPointF((pa.x() + pb.x()) / 2, (pa.y() + pb.y()) / 2)
    target = card._map._hit_test(mid)
    assert target is not None
    assert target["kind"] == "lane"
    assert target["id"] == ("A", "B")


def test_hit_test_empty_returns_none(card):
    from PyQt5.QtCore import QPointF
    card._map.set_waypoints([{"name": "A", "x": 0.0, "y": 0.0}])
    target = card._map._hit_test(QPointF(99999, 99999))
    assert target is None


# ---- Task 22: LINK_PENDING (간선 잇기 — 노드 2회 클릭) ----
def test_short_click_on_node_enters_link_pending(card):
    card._map._edit_mode = True
    card._map._edit_state = "node_pressed"
    card._map._pressed_node = "A"
    card._map._handle_node_short_click("A")
    assert card._map._edit_state == "link_pending"
    assert card._map._selected_node == "A"


def test_second_node_click_emits_lane_create(card, qtbot):
    card._map._edit_mode = True
    card._map._selected_node = "A"
    card._map._edit_state = "link_pending"
    card._map._pressed_node = "B"
    with qtbot.waitSignal(card._map.lane_create_requested, timeout=500) as blocker:
        card._map._handle_node_short_click("B")
    assert blocker.args == ["A", "B"]
    assert card._map._edit_state == "ready"
    assert card._map._selected_node is None


def test_same_node_click_cancels(card):
    card._map._edit_mode = True
    card._map._selected_node = "A"
    card._map._edit_state = "link_pending"
    card._map._handle_node_short_click("A")
    assert card._map._selected_node is None
    assert card._map._edit_state == "ready"


def test_card_on_lane_create_posts(card, monkeypatch):
    called = {}
    import httpx
    class R:
        status_code = 200
        text = ""
    def fake_post(url, json=None, timeout=None):
        called["url"] = url
        called["body"] = json
        return R()
    monkeypatch.setattr(httpx, "post", fake_post)
    card._on_lane_create("A", "B")
    assert called["url"].endswith("/waypoints/lanes")
    assert called["body"] == {"from": "A", "to": "B"}


# ---- Task 23: LANE_SELECTED + Delete 키 ----
def test_delete_key_emits_lane_delete(card, qtbot):
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QKeyEvent
    from PyQt5.QtCore import QEvent
    card._map._edit_mode = True
    card._map._edit_state = "lane_selected"
    card._map._selected_lane = ("A", "B")
    ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
    with qtbot.waitSignal(card._map.lane_delete_requested, timeout=500) as blocker:
        card._map.keyPressEvent(ev)
    assert blocker.args == ["A", "B"]
    assert card._map._edit_state == "ready"
    assert card._map._selected_lane is None


def test_escape_in_edit_resets(card):
    from PyQt5.QtCore import Qt, QEvent
    from PyQt5.QtGui import QKeyEvent
    card._map._edit_mode = True
    card._map._edit_state = "link_pending"
    card._map._selected_node = "A"
    ev = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    card._map.keyPressEvent(ev)
    assert card._map._edit_state == "ready"
    assert card._map._selected_node is None


def test_card_on_lane_delete_calls_endpoint(card, monkeypatch):
    called = {}
    import httpx
    class R:
        status_code = 200
        text = ""
    def fake_request(method, url, json=None, timeout=None):
        called["method"] = method
        called["url"] = url
        called["body"] = json
        return R()
    monkeypatch.setattr(httpx, "request", fake_request)
    card._on_lane_delete("A", "B")
    assert called["method"] == "DELETE"
    assert called["url"].endswith("/waypoints/lanes")
    assert called["body"] == {"from": "A", "to": "B"}
