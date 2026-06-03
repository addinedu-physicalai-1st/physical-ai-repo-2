"""Doctor leader ↔ follower teleop relay — gating + follower fan-out (no ROS).

Wire format: 바이너리 joint frame (streaming.teleop_protocol MSG_JOINTS 0x03).
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from control_service.doctor.teleop_relay import TeleopRelayHub, build_router
from control_service.streaming.teleop_protocol import decode_joints, encode_joints


def _app(hub: TeleopRelayHub) -> FastAPI:
    app = FastAPI()
    app.include_router(build_router(hub))
    return app


def test_leader_forwarded_to_robot_only_when_active() -> None:
    hub = TeleopRelayHub()
    client = TestClient(_app(hub))
    leader = encode_joints(["openarm_left_joint1"], [0.5])

    with client.websocket_connect("/ws/eduping/teleop?role=robot") as robot:
        with client.websocket_connect("/ws/eduping/teleop?role=leader_src") as src:
            # inactive → robot 으로 forward 안 됨.
            src.send_bytes(leader)
            # active → forward (bytes 그대로).
            hub.set_active(True)
            src.send_bytes(leader)
            got = robot.receive_bytes()
            names, positions = decode_joints(got)
            assert names == ["openarm_left_joint1"]
            assert positions == [0.5]


def test_follower_frame_invokes_callback() -> None:
    hub = TeleopRelayHub()
    seen: list[tuple[list, list]] = []
    hub.on_follower(lambda names, pos: seen.append((names, pos)))
    client = TestClient(_app(hub))

    with client.websocket_connect("/ws/eduping/teleop?role=robot") as robot:
        robot.send_bytes(encode_joints(
            ["openarm_left_joint1", "openarm_left_finger_joint1"],
            [0.1, 0.2],
        ))
    assert seen == [(["openarm_left_joint1", "openarm_left_finger_joint1"], [0.1, 0.2])]


def test_bad_role_rejected() -> None:
    hub = TeleopRelayHub()
    client = TestClient(_app(hub))
    import pytest
    from fastapi import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/eduping/teleop?role=bogus") as ws:
            ws.receive_bytes()
    assert exc.value.code == 1008


def test_malformed_follower_frame_ignored() -> None:
    hub = TeleopRelayHub()
    seen: list = []
    hub.on_follower(lambda names, pos: seen.append((names, pos)))
    client = TestClient(_app(hub))

    with client.websocket_connect("/ws/eduping/teleop?role=robot") as robot:
        robot.send_bytes(b"\x00\x01")          # bad magic / 너무 짧음
        robot.send_bytes(b"\xdc\x03\xff\xff")  # mask 16비트 set 인데 값 0개 → too short
    assert seen == []
