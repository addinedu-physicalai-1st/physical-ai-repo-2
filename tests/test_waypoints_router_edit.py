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


# ---- POST /waypoints/click ----
def test_post_click_adds_node(client):
    c, _ = client
    r = c.post("/waypoints/click",
               json={"name": "X", "x": 3.0, "y": 4.0, "yaw": 1.0})
    assert r.status_code == 201
    assert any(w["name"] == "X" for w in r.json()["waypoints"])


def test_post_click_duplicate_name_409(client):
    c, _ = client
    r = c.post("/waypoints/click",
               json={"name": "A", "x": 1, "y": 1, "yaw": 0})
    assert r.status_code == 409


# ---- POST /waypoints/undo ----
def test_undo_after_click(client):
    c, _ = client
    c.post("/waypoints/click", json={"name": "X", "x": 3, "y": 3, "yaw": 0})
    r = c.post("/waypoints/undo")
    assert r.status_code == 200
    assert all(w["name"] != "X" for w in r.json()["waypoints"])


def test_undo_empty_408(client):
    c, _ = client
    # undo stack 비어있는 상태
    from server.control.waypoints import yaml_store as ys
    ys.clear_undo_stack()
    r = c.post("/waypoints/undo")
    assert r.status_code == 408


# ---- POST /waypoints/snapshot-default + reset ----
def test_snapshot_and_reset_roundtrip(client):
    c, _ = client
    # 현재 상태 (A 노드 1개) 를 default 로 동결
    r = c.post("/waypoints/snapshot-default")
    assert r.status_code == 200

    # working 변경
    c.post("/waypoints/click", json={"name": "Y", "x": 7, "y": 7, "yaw": 0})

    # reset — default 로 복구
    r = c.post("/waypoints/reset")
    assert r.status_code == 200
    assert all(w["name"] != "Y" for w in r.json()["waypoints"])


def test_reset_without_default_409(client):
    c, _ = client
    r = c.post("/waypoints/reset")
    assert r.status_code in (404, 409)


# ---- PATCH /waypoints/{name}/rename ----
def test_rename_node(client):
    c, _ = client
    r = c.patch("/waypoints/A/rename", json={"new_name": "Z"})
    assert r.status_code == 200
    body = r.json()
    assert any(w["name"] == "Z" for w in body["waypoints"])
    assert all(w["name"] != "A" for w in body["waypoints"])


def test_rename_unknown_404(client):
    c, _ = client
    r = c.patch("/waypoints/Unknown/rename", json={"new_name": "X"})
    assert r.status_code == 404


def test_rename_nav_active_409(client):
    c, bridge = client
    bridge.health.return_value = {"nav_active": True}
    r = c.patch("/waypoints/A/rename", json={"new_name": "X"})
    assert r.status_code == 409


# ---- GET /waypoints/health 의 nav_active 노출 ----
def test_health_includes_nav_active_field(client):
    c, bridge = client
    bridge.health.return_value = {"nav_active": True, "ros_ok": True}
    r = c.get("/waypoints/health")
    assert r.status_code == 200
    body = r.json()
    assert body["nav_active"] is True
