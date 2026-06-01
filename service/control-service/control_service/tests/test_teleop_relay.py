"""Doctor leader ↔ follower teleop relay — gating + follower fan-out (no ROS)."""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from control_service.doctor.teleop_relay import TeleopRelayHub, build_router


def _app(hub: TeleopRelayHub) -> FastAPI:
    app = FastAPI()
    app.include_router(build_router(hub))
    return app


def test_leader_forwarded_to_robot_only_when_active() -> None:
    hub = TeleopRelayHub()
    client = TestClient(_app(hub))
    leader = json.dumps({"name": ["openarm_left_joint1"], "position": [0.5]})

    with client.websocket_connect("/ws/eduping/teleop?role=robot") as robot:
        with client.websocket_connect("/ws/eduping/teleop?role=leader_src") as src:
            # inactive → robot 으로 forward 안 됨.
            src.send_text(leader)
            # active → forward.
            hub.set_active(True)
            src.send_text(leader)
            got = robot.receive_text()
            assert json.loads(got)["position"] == [0.5]


def test_follower_frame_invokes_callback() -> None:
    hub = TeleopRelayHub()
    seen: list[tuple[list, list]] = []
    hub.on_follower(lambda names, pos: seen.append((names, pos)))
    client = TestClient(_app(hub))

    with client.websocket_connect("/ws/eduping/teleop?role=robot") as robot:
        robot.send_text(json.dumps({
            "name": ["openarm_left_joint1", "openarm_left_finger_joint1"],
            "position": [0.1, 0.2],
        }))
    assert seen == [(["openarm_left_joint1", "openarm_left_finger_joint1"], [0.1, 0.2])]


def test_bad_role_rejected() -> None:
    hub = TeleopRelayHub()
    client = TestClient(_app(hub))
    import pytest
    from fastapi import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/eduping/teleop?role=bogus") as ws:
            ws.receive_text()
    assert exc.value.code == 1008


def test_malformed_follower_json_ignored() -> None:
    hub = TeleopRelayHub()
    seen: list = []
    hub.on_follower(lambda names, pos: seen.append((names, pos)))
    client = TestClient(_app(hub))

    with client.websocket_connect("/ws/eduping/teleop?role=robot") as robot:
        robot.send_text("not-json")
        robot.send_text(json.dumps({"name": ["a"]}))  # position 누락
    assert seen == []
