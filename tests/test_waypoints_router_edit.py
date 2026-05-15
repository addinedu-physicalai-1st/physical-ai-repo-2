"""router 의 노드 편집 endpoint 테스트 — PATCH / click / undo / reset / snapshot."""
from __future__ import annotations

import importlib
import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    wp = tmp_path / "wp.yaml"
    wp.write_text(
        "waypoints:\n"
        "  - {id: 1, name: A, x: 0.0, y: 0.0, yaw: 0.0}\n"
        "patrols: {}\n",
        encoding="utf-8",
    )
    lanes = tmp_path / "lanes.yaml"
    lanes.write_text("lanes: []\n", encoding="utf-8")
    monkeypatch.setenv("PINGDER_WAYPOINTS_FILE", str(wp))
    monkeypatch.setenv("PINGDER_LANES_FILE", str(lanes))
    monkeypatch.setenv("PINGDER_WAYPOINTS_DEFAULT_FILE", str(tmp_path / "wp.default.yaml"))
    monkeypatch.setenv("PINGDER_LANES_DEFAULT_FILE", str(tmp_path / "lanes.default.yaml"))

    import server.control.waypoints.yaml_store as ys_mod
    importlib.reload(ys_mod)
    import server.control.waypoints.router as rt
    importlib.reload(rt)

    app = FastAPI()
    bridge = MagicMock()
    bridge.health.return_value = {"nav_active": False}
    bridge.reload_graph.return_value = {"success": True, "message": "ok"}
    rt.install(app, bridge)
    return TestClient(app), bridge


# ---- PATCH /waypoints/{name} ----
def test_patch_moves_node(client):
    c, _ = client
    r = c.patch("/waypoints/A", json={"x": 5.0, "y": 5.0, "yaw": 1.57})
    assert r.status_code == 200
    wp = next(w for w in r.json()["waypoints"] if w["name"] == "A")
    assert wp["x"] == 5.0 and wp["y"] == 5.0


def test_patch_unknown_404(client):
    c, _ = client
    r = c.patch("/waypoints/Z", json={"x": 0, "y": 0, "yaw": 0})
    assert r.status_code == 404


def test_patch_nav_active_409(client):
    c, bridge = client
    bridge.health.return_value = {"nav_active": True}
    r = c.patch("/waypoints/A", json={"x": 1, "y": 1, "yaw": 0})
    assert r.status_code == 409
