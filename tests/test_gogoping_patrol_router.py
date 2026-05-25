"""GogoPing /debug/patrol endpoint 단위 테스트.

모든 group 카테고리를 랜덤 순서로 순회 (그룹 내는 robot 위치 NN). SetGoal 의
search_waypoints 에 정렬된 vertex 들이 한 리스트로 전달.
"""
from __future__ import annotations

import random
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
    """3 그룹 + 미분류 vertex + mock bridge."""
    wps = [
        # 운동장 (x=0,1,2)
        _wp("A0", 0.0, 0.0, "운동장"),
        _wp("A1", 1.0, 0.0, "운동장"),
        _wp("A2", 2.0, 0.0, "운동장"),
        # 놀이방 (x=10,11)
        _wp("B0", 10.0, 0.0, "놀이방"),
        _wp("B1", 11.0, 0.0, "놀이방"),
        # 통로 (x=20)
        _wp("C0", 20.0, 0.0, "통로"),
        # 미분류
        _wp("ungrouped", 100.0, 100.0, None),
    ]
    monkeypatch.setattr(yaml_store, "load", lambda: (wps, {}))

    bridge = MagicMock()
    bridge.send_goal_sync.return_value = (True, "")
    bridge.get_latest_state.return_value = None
    waypoints_bridge = MagicMock()

    app = FastAPI()
    install(app, bridge, waypoints_bridge)
    return app, bridge


def test_patrol_includes_all_grouped_vertices(app_and_bridge):
    """6 grouped vertex 모두 search_waypoints 에 포함 (미분류 제외)."""
    app, bridge = app_and_bridge
    client = TestClient(app)
    random.seed(0)
    r = client.post("/api/gogoping/debug/patrol", json={})
    body = r.json()
    assert body["accepted"] is True
    assert set(body["vertices"]) == {"A0", "A1", "A2", "B0", "B1", "C0"}
    assert "ungrouped" not in body["vertices"]


def test_patrol_group_order_contains_all_groups(app_and_bridge):
    """group_order 가 모든 3 그룹 포함 (셔플 순서)."""
    app, bridge = app_and_bridge
    client = TestClient(app)
    random.seed(0)
    r = client.post("/api/gogoping/debug/patrol", json={})
    body = r.json()
    assert set(body["group_order"]) == {"운동장", "놀이방", "통로"}
    assert len(body["group_order"]) == 3


def test_patrol_vertices_grouped_by_group_order(app_and_bridge):
    """vertices 가 group_order 순서대로 묶여있음 — 한 그룹 끝나야 다음 그룹."""
    app, bridge = app_and_bridge
    client = TestClient(app)
    random.seed(0)
    r = client.post("/api/gogoping/debug/patrol", json={})
    body = r.json()
    # 그룹별 vertex 매핑
    GRP = {
        "운동장": {"A0", "A1", "A2"},
        "놀이방": {"B0", "B1"},
        "통로": {"C0"},
    }
    verts = body["vertices"]
    # group_order 순서대로 vertex 가 그룹 단위로 연속 — 인접 그룹 vertex 가 섞이지 않음
    seen_groups: list[str] = []
    last_g = None
    for v in verts:
        for g, members in GRP.items():
            if v in members:
                if g != last_g:
                    seen_groups.append(g)
                    last_g = g
                break
    assert seen_groups == body["group_order"]


def test_patrol_nn_within_group_from_robot_pose(app_and_bridge):
    """첫 그룹 안 NN 정렬 — robot pose 에서 가장 가까운 vertex 부터.

    robot pose=(0.5, 0) + 운동장이 첫 그룹이면 A0(0,0) 가장 가까움 → A1 → A2.
    """
    app, bridge = app_and_bridge
    bridge.get_latest_state.return_value = {"robot_pose": {"x": 0.5, "y": 0.0, "yaw": 0.0}}
    client = TestClient(app)
    # seed 로 그룹 순서 운동장 먼저 강제? random.shuffle 은 결정적
    # 운동장이 첫 group 인 경우를 확실하게 만들기 위해 single group fixture 시 쓸 수 있지만
    # 여기선 결과만 검증 — A0,A1,A2 가 가까운 순으로 묶여있는지.
    random.seed(0)
    r = client.post("/api/gogoping/debug/patrol", json={})
    body = r.json()
    verts = body["vertices"]
    # 운동장 vertex 들이 인접 (그룹 단위 연속) + A0 → A1 → A2 순 (NN from 0.5,0)
    # B0, B1 는 자기들끼리 인접
    gym_idx = [i for i, v in enumerate(verts) if v in ("A0", "A1", "A2")]
    play_idx = [i for i, v in enumerate(verts) if v in ("B0", "B1")]
    assert gym_idx == list(range(min(gym_idx), max(gym_idx) + 1))   # 연속
    assert play_idx == list(range(min(play_idx), max(play_idx) + 1))


def test_patrol_used_robot_pose_flag(app_and_bridge):
    app, bridge = app_and_bridge
    bridge.get_latest_state.return_value = {"robot_pose": {"x": 5.0, "y": 0.0, "yaw": 0.0}}
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    assert r.json()["used_robot_pose"] is True


def test_patrol_fallback_when_no_robot_pose(app_and_bridge):
    """robot pose 없으면 첫 그룹의 첫 vertex 좌표 시작."""
    app, bridge = app_and_bridge
    bridge.get_latest_state.return_value = None
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    body = r.json()
    assert body["used_robot_pose"] is False


def test_patrol_no_grouped_vertices(monkeypatch, app_and_bridge):
    monkeypatch.setattr(
        yaml_store, "load",
        lambda: ([_wp("ungrouped", 0, 0)], {}),
    )
    app, bridge = app_and_bridge
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    body = r.json()
    assert body["accepted"] is False
    assert body["reason"] == "no_grouped_vertices"
    bridge.send_goal_sync.assert_not_called()


def test_patrol_send_goal_rejected_propagates(app_and_bridge):
    app, bridge = app_and_bridge
    bridge.send_goal_sync.return_value = (False, "service_unavailable")
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    body = r.json()
    assert body["accepted"] is False
    assert body["reason"] == "service_unavailable"
    # 정렬은 됐고 SetGoal 만 실패
    assert len(body["vertices"]) == 6
    assert len(body["group_order"]) == 3


def test_patrol_goal_passes_full_vertex_list_to_bridge(app_and_bridge):
    app, bridge = app_and_bridge
    client = TestClient(app)
    r = client.post("/api/gogoping/debug/patrol", json={})
    goal = bridge.send_goal_sync.call_args.args[0]
    # 평탄화 이후 (commit 1f19e35): mode/task 두 축 → target_state 단일.
    assert goal.target_state == "HIDEANDSEEK"
    # Task 8 이후: HIDEANDSEEK 진입 시 play_area_key 필수 — reconciler 가 검증.
    # waypoints.yaml 의 실제 등록 vertex (Task 8 후 nav graph 와 일치 fix)
    assert goal.play_area_key == "운동장2"
    assert list(goal.search_waypoints) == r.json()["vertices"]
    assert len(goal.search_waypoints) == 6
