"""GogoPing /debug/patrol endpoint 단위 테스트.

waypoints.yaml 의 ``group`` 필드 있는 모든 vertex 를 robot 의 현재 위치에서
nearest-neighbor 순서로 정렬 → SetGoal(PLAY/hideseek, search_waypoints=[...]) 호출.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "service" / "control-service"))

from control_service.gogoping.router import install
from control_service.waypoints import yaml_store


def _wp(name, x, y, group=None):
    return yaml_store.Waypoint(name=name, x=float(x), y=float(y), yaw=0.0, group=group)


@pytest.fixture
def app_and_bridge(monkeypatch):
    """4 group vertex (좌표 직선상) + 미분류 vertex + mock bridge."""
    # x=0,1,2,3,4 일렬 — nearest-neighbor 순서 검증 쉬움
    wps = [
        _wp("A", 0.0, 0.0, "운동장"),
        _wp("B", 1.0, 0.0, "운동장"),
        _wp("C", 2.0, 0.0, "놀이방"),
        _wp("D", 3.0, 0.0, "수면실"),
        _wp("E", 4.0, 0.0, "출입구"),
        _wp("복도1", 10.0, 10.0, None),  # 미분류 — patrol 제외
        _wp("복도2", -10.0, -10.0, None),
    ]
    monkeypatch.setattr(yaml_store, "load", lambda: (wps, {}))

    bridge = MagicMock()
    bridge.send_goal_sync.return_value = (True, "")
    bridge.get_latest_state.return_value = None  # 기본: robot pose 없음
    waypoints_bridge = MagicMock()

    app = FastAPI()
    install(app, bridge, waypoints_bridge)
    return app, bridge


def test_patrol_collects_all_grouped_vertices(app_and_bridge):
    """모든 group 있는 vertex 가 search_waypoints 에 포함 (5개) — 미분류 2개 제외."""
    app, bridge = app_and_bridge
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] is True
    assert set(body["vertices"]) == {"A", "B", "C", "D", "E"}
    assert len(body["vertices"]) == 5


def test_patrol_excludes_ungrouped_vertices(app_and_bridge):
    """group=None 인 vertex 는 어떤 경우에도 search_waypoints 에 포함 안 됨."""
    app, bridge = app_and_bridge
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    verts = r.json()["vertices"]
    assert "복도1" not in verts
    assert "복도2" not in verts


def test_patrol_nearest_neighbor_from_robot_pose(app_and_bridge):
    """robot pose=(2.5, 0) 일 때 → C(2,0) 가 가장 가까움. 그 다음 B(1)?D(3)?

    C(2) → 인접 후보: B(1) dist=1, D(3) dist=1. min() 가 첫 발견 우선 — B 가 list 에서
    먼저라 B 선택. 그 다음 A(0), 마지막 D(3) → E(4).
    """
    app, bridge = app_and_bridge
    bridge.get_latest_state.return_value = {"robot_pose": {"x": 2.5, "y": 0.0, "yaw": 0.0}}
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    body = r.json()
    assert body["used_robot_pose"] is True
    assert body["start_x"] == 2.5
    # 시작점 (2.5,0) — 가장 가까운: C(2,0). 그 다음 C(2)→B(1)(dist 1) 우선 (list 순서).
    # 그 다음 B→A(0). 그 다음 A→D(3) dist=3, E(4) dist=4 → D. 마지막 E.
    assert body["vertices"] == ["C", "B", "A", "D", "E"]


def test_patrol_nearest_neighbor_from_other_pose(app_and_bridge):
    """robot pose=(10, 0) → 가장 가까운 E(4). 그 다음 D(3), C(2), B(1), A(0)."""
    app, bridge = app_and_bridge
    bridge.get_latest_state.return_value = {"robot_pose": {"x": 10.0, "y": 0.0, "yaw": 0.0}}
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    assert r.json()["vertices"] == ["E", "D", "C", "B", "A"]


def test_patrol_fallback_when_no_robot_pose(app_and_bridge):
    """bridge.get_latest_state() 가 None → 첫 vertex 좌표를 시작점으로."""
    app, bridge = app_and_bridge
    bridge.get_latest_state.return_value = None
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    body = r.json()
    assert body["accepted"] is True
    assert body["used_robot_pose"] is False
    # 첫 후보 A(0,0) 부터 시작 → A, B, C, D, E
    assert body["vertices"] == ["A", "B", "C", "D", "E"]


def test_patrol_fallback_when_pose_missing_fields(app_and_bridge):
    """robot_pose dict 안에 x/y 없으면 fallback."""
    app, bridge = app_and_bridge
    bridge.get_latest_state.return_value = {"robot_pose": {}}
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    body = r.json()
    assert body["used_robot_pose"] is False
    assert body["vertices"] == ["A", "B", "C", "D", "E"]


def test_patrol_no_grouped_vertices(monkeypatch, app_and_bridge):
    """모든 vertex 가 미분류 → no_grouped_vertices."""
    monkeypatch.setattr(
        yaml_store, "load",
        lambda: ([_wp("복도1", 0, 0), _wp("복도2", 1, 1)], {}),
    )
    app, bridge = app_and_bridge
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    body = r.json()
    assert body["accepted"] is False
    assert body["reason"] == "no_grouped_vertices"
    bridge.send_goal_sync.assert_not_called()


def test_patrol_send_goal_rejected_propagates(app_and_bridge):
    """bridge.send_goal_sync 가 (False, reason) 반환 시 그대로 전파, vertices 는 echo."""
    app, bridge = app_and_bridge
    bridge.send_goal_sync.return_value = (False, "service_unavailable")
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    body = r.json()
    assert body["accepted"] is False
    assert body["reason"] == "service_unavailable"
    assert len(body["vertices"]) == 5  # 정렬은 됐고 SetGoal 만 실패


def test_patrol_goal_passes_search_waypoints_to_bridge(app_and_bridge):
    """bridge.send_goal_sync 가 받은 Goal 의 search_waypoints 가 응답 vertices 와 일치."""
    app, bridge = app_and_bridge
    bridge.get_latest_state.return_value = {"robot_pose": {"x": 10.0, "y": 0.0, "yaw": 0.0}}
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    goal = bridge.send_goal_sync.call_args.args[0]
    assert goal.mode == "PLAY"
    assert goal.task == "hideseek"
    assert list(goal.search_waypoints) == r.json()["vertices"] == ["E", "D", "C", "B", "A"]
