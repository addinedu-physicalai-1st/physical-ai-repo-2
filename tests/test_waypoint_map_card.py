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


def test_sse_event_route_path_sets_points(qtbot, card):
    """graph_router /route_path 중계 → 좌표 시퀀스 강조선. RViz 와 동일 소스라
    BT 자율주행(navigate 미경유)에서도 admin 에 L1 경로가 표시된다."""
    from widgets.waypoint_map_card import _SseDispatcher
    d = _SseDispatcher(card)
    d.handle({"type": "route_path", "points": [[1.0, 2.0], [3.5, 4.5]]})
    assert card._map._route_points == [(1.0, 2.0), (3.5, 4.5)]


def test_sse_event_route_path_empty_clears(qtbot, card):
    """종료 시 graph_router 가 빈 Path 를 latch → 경로 해제."""
    from widgets.waypoint_map_card import _SseDispatcher
    d = _SseDispatcher(card)
    d.handle({"type": "route_path", "points": [[1.0, 2.0], [3.5, 4.5]]})
    d.handle({"type": "route_path", "points": []})
    assert card._map._route_points == []
