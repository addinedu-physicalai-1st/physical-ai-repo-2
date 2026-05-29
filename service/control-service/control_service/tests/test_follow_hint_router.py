"""POST /api/gogoping/follow/hint 라우터 단위 테스트."""
import sys
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ROS 미source 환경에서도 import 통과
sys.modules.setdefault("std_msgs", MagicMock())
sys.modules.setdefault("std_msgs.msg", MagicMock())

from control_service.routers import gogoping_follow as follow_router  # noqa: E402


@pytest.fixture
def client_with_mock():
    """publish_follow_hint 만 mock 한 최소 FastAPI app."""
    app = FastAPI()
    app.include_router(follow_router.router)
    mock_publish = MagicMock()
    original = follow_router.publish_follow_hint
    follow_router.publish_follow_hint = mock_publish  # type: ignore[assignment]
    yield TestClient(app), mock_publish
    follow_router.publish_follow_hint = original  # type: ignore[assignment]


def test_hint_valid_right_publishes(client_with_mock):
    test_client, mock_publish = client_with_mock
    r = test_client.post("/api/gogoping/follow/hint", json={"direction": "right"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "published": "right"}
    mock_publish.assert_called_once_with("right")


def test_hint_valid_left(client_with_mock):
    test_client, mock_publish = client_with_mock
    r = test_client.post("/api/gogoping/follow/hint", json={"direction": "left"})
    assert r.status_code == 200
    mock_publish.assert_called_once_with("left")


def test_hint_invalid_direction(client_with_mock):
    test_client, mock_publish = client_with_mock
    r = test_client.post("/api/gogoping/follow/hint", json={"direction": "up"})
    assert r.status_code == 422  # pydantic validation
    mock_publish.assert_not_called()


def test_hint_search_valid(client_with_mock):
    test_client, mock_publish = client_with_mock
    r = test_client.post("/api/gogoping/follow/hint", json={"direction": "search"})
    assert r.status_code == 200
    mock_publish.assert_called_once_with("search")


def test_hint_resume_valid(client_with_mock):
    test_client, mock_publish = client_with_mock
    r = test_client.post("/api/gogoping/follow/hint", json={"direction": "resume"})
    assert r.status_code == 200
    mock_publish.assert_called_once_with("resume")


def test_hint_bridge_not_ready():
    """publish_follow_hint 가 None 이면 503."""
    app = FastAPI()
    app.include_router(follow_router.router)
    original = follow_router.publish_follow_hint
    follow_router.publish_follow_hint = None  # type: ignore[assignment]
    try:
        client = TestClient(app)
        r = client.post("/api/gogoping/follow/hint", json={"direction": "right"})
        assert r.status_code == 503
    finally:
        follow_router.publish_follow_hint = original  # type: ignore[assignment]
