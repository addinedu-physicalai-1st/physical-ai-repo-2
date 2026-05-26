"""WSS doctor teleop handler — without ROS (Task 3)."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi import WebSocketDisconnect
from control_service.doctor.teleop_ws import (
    DoctorTeleopHub, build_router,
)
from control_service.streaming.teleop_protocol import (
    TargetFrame, ArmTarget, StateFrame, ArmState,
    encode_target, decode_target, encode_state, decode_state,
    SERVO_STATUS_OK,
)


def _app(hub: DoctorTeleopHub) -> FastAPI:
    app = FastAPI()
    app.include_router(build_router(hub))
    return app


def test_target_frame_dispatch_to_hub() -> None:
    hub = DoctorTeleopHub()
    received: list[TargetFrame] = []
    hub.on_target(lambda eid, frame: received.append(frame))

    client = TestClient(_app(hub))
    with client.websocket_connect("/ws/doctor/teleop?eduping_id=ed-01") as ws:
        ws.send_bytes(encode_target(TargetFrame(
            ts_ms=1, left=ArmTarget(0.3, 0.1, 0.4, 0, 0, 0, 1, 0.5), right=None,
        )))
        # close → server processes
    assert len(received) == 1
    assert received[0].left is not None
    assert received[0].left.x == pytest.approx(0.3, abs=1e-3)


def test_state_broadcast_to_client() -> None:
    hub = DoctorTeleopHub()
    client = TestClient(_app(hub))
    with client.websocket_connect("/ws/doctor/teleop?eduping_id=ed-01") as ws:
        # hub 가 push 하는 state 가 client 로 가는지
        state = StateFrame(
            ts_ms=2,
            left=ArmState(joints=[0]*7, gripper=0.1, servo_status=SERVO_STATUS_OK),
            right=ArmState(joints=[0]*7, gripper=0.1, servo_status=SERVO_STATUS_OK),
        )
        hub.publish_state("ed-01", state)
        data = ws.receive_bytes()
        decoded = decode_state(data)
        assert decoded.ts_ms == 2


def test_json_session_messages_are_relayed() -> None:
    hub = DoctorTeleopHub()
    seen: list[dict] = []
    hub.on_event(lambda eid, msg: seen.append(msg))
    client = TestClient(_app(hub))
    with client.websocket_connect("/ws/doctor/teleop?eduping_id=ed-01") as ws:
        ws.send_text('{"type":"session","action":"end"}')
    assert seen == [{"type": "session", "action": "end"}]


def test_missing_eduping_id_rejected() -> None:
    hub = DoctorTeleopHub()
    client = TestClient(_app(hub))
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/ws/doctor/teleop") as ws:
            ws.receive_bytes()
    assert exc_info.value.code == 1008
