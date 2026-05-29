"""/ws/follow-state — follow_state callback fan-out 단위테스트."""
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("std_msgs", MagicMock())
sys.modules.setdefault("std_msgs.msg", MagicMock())

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from control_service.routers import gogoping_follow as follow_router


def _make_bridge_mock(current: str | None = "idle"):
    bridge = MagicMock()
    registered = {"cb": None}

    def reg_cb(cb):
        registered["cb"] = cb
        return lambda: None

    bridge.register_follow_state_callback = reg_cb
    bridge.current_follow_state = MagicMock(return_value=current)
    return bridge, registered


def test_follow_state_ws_sends_initial_mode_on_connect():
    app = FastAPI()
    bridge, _ = _make_bridge_mock(current="voice_search")
    follow_router._install_follow_state_ws(app, bridge)
    with TestClient(app).websocket_connect("/ws/follow-state") as ws:
        msg = ws.receive_json()
        assert msg == {"mode": "voice_search"}


def test_follow_state_ws_skips_initial_if_no_state():
    """current_follow_state=None 이면 초기 send 생략 — 다음 callback 호출까지 대기."""
    app = FastAPI()
    bridge, _ = _make_bridge_mock(current=None)
    follow_router._install_follow_state_ws(app, bridge)
    # 연결 후 즉시 끊어 큐가 비어있는 채로 종료 가능 — 에러 없이 처리
    with TestClient(app).websocket_connect("/ws/follow-state") as ws:
        # 메시지 없음 — 클라이언트 즉시 disconnect
        pass


def test_follow_state_ws_register_unregister_callback():
    """callback 이 connect 시 등록 + disconnect 시 unregister 되는지."""
    app = FastAPI()
    unreg_called = {"flag": False}

    def reg_cb(cb):
        def _u():
            unreg_called["flag"] = True
        return _u

    bridge = MagicMock()
    bridge.register_follow_state_callback = reg_cb
    bridge.current_follow_state = MagicMock(return_value=None)
    follow_router._install_follow_state_ws(app, bridge)

    with TestClient(app).websocket_connect("/ws/follow-state"):
        pass
    assert unreg_called["flag"] is True
