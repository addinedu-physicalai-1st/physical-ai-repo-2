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
        'width="881" height="720"><rect width="881" height="720" fill="#FAF7F2"/></svg>',
        encoding="utf-8",
    )
    monkeypatch.setenv("PINGDER_ADMIN_MAP_SVG", str(svg))
    from widgets.waypoint_map_card import WaypointMapCard
    w = WaypointMapCard(control_url="http://localhost:0")
    qtbot.addWidget(w)
    return w


def test_card_creates_without_error(card):
    assert card is not None


def test_card_loads_svg(card):
    assert card._svg_renderer is not None
    assert card._svg_renderer.isValid()


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
