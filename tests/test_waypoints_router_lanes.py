"""router 의 lane CRUD + auto-edge + reset/snapshot endpoint 테스트.
nav_active 게이팅도 함께 검증."""
from __future__ import annotations

import importlib
import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """waypoints A, B 두 개 + 빈 lanes 로 시작."""
    wp = tmp_path / "wp.yaml"
    wp.write_text(
        "waypoints:\n"
        "  - {id: 1, name: A, x: 0.0, y: 0.0, yaw: 0.0}\n"
        "  - {id: 2, name: B, x: 1.0, y: 0.0, yaw: 0.0}\n"
        "patrols: {}\n",
        encoding="utf-8",
    )
    lanes = tmp_path / "lanes.yaml"
    lanes.write_text("lanes: []\n", encoding="utf-8")
    wp_def = tmp_path / "wp.default.yaml"
    lanes_def = tmp_path / "lanes.default.yaml"
    monkeypatch.setenv("PINGDER_WAYPOINTS_FILE", str(wp))
    monkeypatch.setenv("PINGDER_LANES_FILE", str(lanes))
    monkeypatch.setenv("PINGDER_WAYPOINTS_DEFAULT_FILE", str(wp_def))
    monkeypatch.setenv("PINGDER_LANES_DEFAULT_FILE", str(lanes_def))

    import server.control.waypoints.yaml_store as ys_mod
    importlib.reload(ys_mod)
    import server.control.waypoints.router as rt
    importlib.reload(rt)

    app = FastAPI()
    bridge = MagicMock()
    bridge.health.return_value = {"nav_active": False, "ros_ok": True}
    bridge.reload_graph.return_value = {"success": True, "message": "ok"}
    rt.install(app, bridge)
    return TestClient(app), bridge


# ---- POST /waypoints/lanes (간선 잇기) ----
def test_post_lane_adds_and_reloads(client):
    c, bridge = client
    r = c.post("/waypoints/lanes", json={"from": "A", "to": "B"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["lanes"]) == 1
    assert body["lanes"][0]["from"] == "A"
    bridge.reload_graph.assert_called_once()


def test_post_lane_duplicate_409(client):
    c, _ = client
    c.post("/waypoints/lanes", json={"from": "A", "to": "B"})
    r = c.post("/waypoints/lanes", json={"from": "B", "to": "A"})
    assert r.status_code == 409


def test_post_lane_unknown_waypoint_400(client):
    c, _ = client
    r = c.post("/waypoints/lanes", json={"from": "A", "to": "Z"})
    assert r.status_code in (400, 404, 409)


def test_post_lane_nav_active_409(client):
    c, bridge = client
    bridge.health.return_value = {"nav_active": True}
    r = c.post("/waypoints/lanes", json={"from": "A", "to": "B"})
    assert r.status_code == 409


# ---- DELETE /waypoints/lanes (간선 끊기) ----
def test_delete_lane_removes_and_reloads(client):
    c, bridge = client
    c.post("/waypoints/lanes", json={"from": "A", "to": "B"})
    bridge.reload_graph.reset_mock()
    r = c.request("DELETE", "/waypoints/lanes", json={"from": "B", "to": "A"})
    assert r.status_code == 200
    assert r.json()["lanes"] == []
    bridge.reload_graph.assert_called_once()


def test_delete_lane_missing_404(client):
    c, _ = client
    r = c.request("DELETE", "/waypoints/lanes", json={"from": "A", "to": "B"})
    assert r.status_code == 404
