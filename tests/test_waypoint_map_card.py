import pytest
from pathlib import Path

pytest.importorskip("pytestqt")
pytest.importorskip("PyQt5")


@pytest.fixture
def card(qtbot, tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/admin-app"))
    pgm = tmp_path / "map_v2.pgm"
    # 최소 P5 PGM (2x2, 전부 흰색). QPixmap 이 valid 로 로드 가능.
    pgm.write_bytes(b"P5\n2 2\n255\n\xff\xff\xff\xff")
    monkeypatch.setenv("PINGDER_ADMIN_MAP_PGM", str(pgm))
    from widgets.waypoint_map_card import WaypointMapCard
    w = WaypointMapCard(control_url="http://localhost:0")
    qtbot.addWidget(w)
    return w


def test_card_creates_without_error(card):
    assert card is not None


def test_card_loads_map(card):
    assert card._map_pixmap is not None
    assert not card._map_pixmap.isNull()


def test_sse_event_updates_robot(qtbot, card):
    from widgets.waypoint_map_card import _SseDispatcher
    dispatcher = _SseDispatcher(card)
    dispatcher.handle({"type": "odom", "x": 1.0, "y": 2.0, "yaw": 0.5})
    assert card._map._robot == {"x": 1.0, "y": 2.0, "yaw": 0.5}


def test_sse_event_updates_plan(qtbot, card):
    from widgets.waypoint_map_card import _SseDispatcher
    d = _SseDispatcher(card)
    d.handle({"type": "plan", "points": [[0.0, 0.0], [1.0, 1.0]]})
    assert card._map._plan == [(0.0, 0.0), (1.0, 1.0)]


def test_sse_event_updates_goal_status(qtbot, card):
    from widgets.waypoint_map_card import _SseDispatcher
    d = _SseDispatcher(card)
    d.handle({"type": "goal_status", "name": "수면실", "status": "active"})
    assert "수면실" in card._status.text()
    d.handle({"type": "goal_status", "name": "수면실", "status": "succeeded"})
    assert card._status.text() == ""
