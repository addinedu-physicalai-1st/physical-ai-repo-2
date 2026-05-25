"""hideseek recruit-complete / caught REST API — bridge mock 으로 handler 검증.

ros_bridge 의 ``write_hideseek_registered_ids`` / ``append_hideseek_caught_id`` 가
정확히 호출되는지, response 가 schema 대로 나오는지만 확인. 실제 SetBlackboard.srv
호출은 bridge 단위 테스트에서.
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


@pytest.fixture
def app_and_bridge():
    """install() 에 mock bridge + mock waypoints_bridge 주입."""
    bridge = MagicMock()
    # 기본값: 성공
    bridge.write_hideseek_registered_ids.return_value = (True, "")
    bridge.append_hideseek_caught_id.return_value = (True, "")
    waypoints_bridge = MagicMock()

    app = FastAPI()
    install(app, bridge, waypoints_bridge)
    return app, bridge


def test_recruit_complete_writes_registered_ids(app_and_bridge):
    """POST recruit-complete → bridge.write_hideseek_registered_ids([1, 3, 7]) 호출."""
    app, bridge = app_and_bridge
    client = TestClient(app)
    r = client.post(
        "/api/gogoping/play/hideseek/recruit-complete",
        json={"child_ids": [1, 3, 7]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"accepted": True, "reason": "", "count": 3}
    bridge.write_hideseek_registered_ids.assert_called_once_with([1, 3, 7])


def test_recruit_complete_empty_list_allowed(app_and_bridge):
    """빈 child_ids 도 (UI 가 막을 책임) handler 는 통과시킴."""
    app, bridge = app_and_bridge
    client = TestClient(app)
    r = client.post(
        "/api/gogoping/play/hideseek/recruit-complete",
        json={"child_ids": []},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["accepted"] is True
    bridge.write_hideseek_registered_ids.assert_called_once_with([])


def test_recruit_complete_propagates_bridge_failure(app_and_bridge):
    """bridge 가 (False, reason) 반환 시 accepted=False."""
    app, bridge = app_and_bridge
    bridge.write_hideseek_registered_ids.return_value = (False, "service_unavailable")
    client = TestClient(app)
    r = client.post(
        "/api/gogoping/play/hideseek/recruit-complete",
        json={"child_ids": [1, 2]},
    )
    body = r.json()
    assert body["accepted"] is False
    assert body["reason"] == "service_unavailable"
    assert body["count"] == 2


def test_recruit_complete_missing_field_returns_422(app_and_bridge):
    """child_ids 누락 시 pydantic 검증 실패 → 422."""
    app, bridge = app_and_bridge
    client = TestClient(app)
    r = client.post("/api/gogoping/play/hideseek/recruit-complete", json={})
    assert r.status_code == 422
    bridge.write_hideseek_registered_ids.assert_not_called()


def test_caught_appends_child_id(app_and_bridge):
    """POST caught → bridge.append_hideseek_caught_id(5) 호출."""
    app, bridge = app_and_bridge
    client = TestClient(app)
    r = client.post(
        "/api/gogoping/play/hideseek/caught",
        json={"child_id": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"accepted": True, "reason": "", "child_id": 5}
    bridge.append_hideseek_caught_id.assert_called_once_with(5)


def test_caught_accepts_optional_waypoint(app_and_bridge):
    """caught_at_waypoint 는 옵셔널 — bridge 호출에는 미전달 (BT 가 사용 안 함)."""
    app, bridge = app_and_bridge
    client = TestClient(app)
    r = client.post(
        "/api/gogoping/play/hideseek/caught",
        json={"child_id": 9, "caught_at_waypoint": "운동장2_NW"},
    )
    assert r.status_code == 200
    bridge.append_hideseek_caught_id.assert_called_once_with(9)


def test_caught_propagates_bridge_failure(app_and_bridge):
    """bridge 가 (False, reason) 반환 시 accepted=False."""
    app, bridge = app_and_bridge
    bridge.append_hideseek_caught_id.return_value = (False, "timeout")
    client = TestClient(app)
    r = client.post(
        "/api/gogoping/play/hideseek/caught",
        json={"child_id": 11},
    )
    body = r.json()
    assert body["accepted"] is False
    assert body["reason"] == "timeout"
    assert body["child_id"] == 11


def test_caught_missing_child_id_returns_422(app_and_bridge):
    """child_id 누락 시 422."""
    app, bridge = app_and_bridge
    client = TestClient(app)
    r = client.post("/api/gogoping/play/hideseek/caught", json={})
    assert r.status_code == 422
    bridge.append_hideseek_caught_id.assert_not_called()
