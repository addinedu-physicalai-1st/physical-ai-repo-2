import json
import pytest
from unittest.mock import MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from control_service.waypoints.router import install


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PINGDER_WAYPOINTS_FILE", str(tmp_path / "wp.yaml"))
    # yaml_store 모듈 reload (env var 반영)
    import importlib
    import control_service.waypoints.yaml_store as ys_mod
    importlib.reload(ys_mod)
    import control_service.waypoints.router as rt
    importlib.reload(rt)

    app = FastAPI()
    bridge = MagicMock()
    bridge.health.return_value = {
        "ros_ok": True, "nav_action_available": True,
        "odom_age_ms": 100, "plan_age_ms": 200, "ros_domain_id": 210,
    }
    rt.install(app, bridge)
    return TestClient(app), bridge


# ---- Task 10: GET ----
def test_get_waypoints_empty(client):
    c, _ = client
    r = c.get("/waypoints")
    assert r.status_code == 200
    assert r.json() == {"waypoints": [], "patrols": {}, "lanes": []}


# ---- Task 11: POST / DELETE ----
def test_post_waypoint_with_odom(client):
    c, bridge = client
    bridge.odom_snapshot.return_value = (1.5, -2.5, 0.78)
    r = c.post("/waypoints", json={"name": "수면실"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "수면실"
    assert body["x"] == 1.5
    g = c.get("/waypoints").json()
    assert g["waypoints"][0]["name"] == "수면실"


def test_post_waypoint_without_odom(client):
    c, bridge = client
    bridge.odom_snapshot.return_value = None
    r = c.post("/waypoints", json={"name": "수면실"})
    assert r.status_code == 409
    assert "odom" in r.json()["detail"]


def test_post_waypoint_duplicate(client):
    c, bridge = client
    bridge.odom_snapshot.return_value = (0, 0, 0)
    c.post("/waypoints", json={"name": "수면실"})
    r = c.post("/waypoints", json={"name": "수면실"})
    assert r.status_code == 409


def test_post_waypoint_empty_name(client):
    c, _ = client
    r = c.post("/waypoints", json={"name": ""})
    assert r.status_code == 422


def test_delete_waypoint(client):
    c, bridge = client
    bridge.odom_snapshot.return_value = (0, 0, 0)
    c.post("/waypoints", json={"name": "수면실"})
    r = c.delete("/waypoints/수면실")
    assert r.status_code == 200
    g = c.get("/waypoints").json()
    assert g["waypoints"] == []


def test_delete_waypoint_in_patrol(client, tmp_path):
    c, bridge = client
    bridge.odom_snapshot.return_value = (0, 0, 0)
    c.post("/waypoints", json={"name": "수면실"})
    import yaml as pyyaml
    p = tmp_path / "wp.yaml"
    data = pyyaml.safe_load(p.read_text())
    data["patrols"] = {"hide_and_seek_search": ["수면실"]}
    p.write_text(pyyaml.safe_dump(data, allow_unicode=True))
    r = c.delete("/waypoints/수면실")
    assert r.status_code == 409


# ---- Task 12: Goto / Patrol / Cancel / Health ----
def test_goto_existing(client):
    c, bridge = client
    bridge.odom_snapshot.return_value = (1.0, 2.0, 0.5)
    c.post("/waypoints", json={"name": "수면실"})
    r = c.post("/waypoints/goto", json={"name": "수면실"})
    assert r.status_code == 202
    body = r.json()
    assert body["name"] == "수면실"
    assert "goal_id" in body and len(body["goal_id"]) > 8
    bridge.navigate_to_pose.assert_called_once()
    args = bridge.navigate_to_pose.call_args.args
    assert args[0] == 1.0 and args[1] == 2.0 and args[2] == 0.5


def test_goto_missing(client):
    c, _ = client
    r = c.post("/waypoints/goto", json={"name": "없음"})
    assert r.status_code == 404


def test_goto_pose_with_coords(client):
    """RViz Nav2 Goal 패턴 — 좌표 직접 지정으로 NavigateToPose 호출."""
    c, bridge = client
    r = c.post("/waypoints/goto-pose", json={"x": 1.5, "y": -2.5, "yaw": 0.78})
    assert r.status_code == 202
    body = r.json()
    assert body["x"] == 1.5 and body["y"] == -2.5 and body["yaw"] == 0.78
    assert body["name"] == "(click)"
    assert "goal_id" in body and len(body["goal_id"]) > 8
    bridge.navigate_to_pose.assert_called_once()
    args = bridge.navigate_to_pose.call_args.args
    assert args[0] == 1.5 and args[1] == -2.5 and args[2] == 0.78


def test_goto_pose_missing_fields(client):
    """x/y/yaw 중 하나라도 빠지면 422."""
    c, _ = client
    r = c.post("/waypoints/goto-pose", json={"x": 1.0, "y": 2.0})  # yaw 빠짐
    assert r.status_code == 422


def test_patrol_calls_bridge(client, tmp_path):
    c, bridge = client
    bridge.odom_snapshot.return_value = (0, 0, 0)
    c.post("/waypoints", json={"name": "a"})
    bridge.odom_snapshot.return_value = (1, 1, 0)
    c.post("/waypoints", json={"name": "b"})
    import yaml as pyyaml
    p = tmp_path / "wp.yaml"
    data = pyyaml.safe_load(p.read_text())
    data["patrols"] = {"hide_and_seek_search": ["a", "b"]}
    p.write_text(pyyaml.safe_dump(data, allow_unicode=True))

    r = c.post("/waypoints/patrol/hide_and_seek_search")
    assert r.status_code == 202
    bridge.follow_waypoints.assert_called_once()
    wps = bridge.follow_waypoints.call_args.args[0]
    assert len(wps) == 2


def test_get_patrol_lookup(client, tmp_path):
    c, bridge = client
    bridge.odom_snapshot.return_value = (0, 0, 0)
    c.post("/waypoints", json={"name": "a"})
    import yaml as pyyaml
    p = tmp_path / "wp.yaml"
    data = pyyaml.safe_load(p.read_text())
    data["patrols"] = {"hide_and_seek_search": ["a"]}
    p.write_text(pyyaml.safe_dump(data, allow_unicode=True))

    r = c.get("/waypoints/patrol/hide_and_seek_search")
    assert r.status_code == 200
    assert r.json()["waypoints"][0]["name"] == "a"


def test_cancel_calls_bridge(client):
    c, bridge = client
    r = c.post("/waypoints/cancel")
    assert r.status_code == 200
    bridge.cancel_current.assert_called_once()


def test_health(client):
    c, _ = client
    r = c.get("/waypoints/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ros_ok"] is True
    assert "map_drift" in body
