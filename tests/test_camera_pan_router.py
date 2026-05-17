"""control_service.camera_pan.router 단위 테스트.

CameraPanBridge 는 mock — rclpy 없이도 실행 가능. teleop_router 패턴과 동일.
"""

from __future__ import annotations

import asyncio
import os
import time
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from control_service.camera_pan import router as router_mod
from control_service.camera_pan.ros_bridge import (
    PAN_JOINT,
    TILT_JOINT,
    TOPIC_CMD_PAN,
    TOPIC_CMD_TILT,
    TOPIC_STATE,
    CameraPanBridge,
)


def _mock_bridge() -> MagicMock:
    m = MagicMock(spec=CameraPanBridge)
    m._snap = {"pan_deg": 90.0, "tilt_deg": 90.0, "age_ms": 10, "ros_ok": True}
    m.snapshot.side_effect = lambda: dict(m._snap)
    m.health.return_value = {
        "ros_domain_id": int(os.environ.get("ROS_DOMAIN_ID", "0")),
        "ros_ok": True,
        "last_state_age_ms": 10,
    }
    m.pan_calls = []
    m.tilt_calls = []
    m.publish_pan.side_effect = lambda d: m.pan_calls.append(d)
    m.publish_tilt.side_effect = lambda d: m.tilt_calls.append(d)
    return m


def _make_app(bridge) -> FastAPI:
    app = FastAPI()
    router_mod.install(app, bridge)
    return app


# ── POST /camera_pan/cmd ────────────────────────────────────────────────────


def test_post_cmd_pan_only_calls_publish_pan() -> None:
    bridge = _mock_bridge()
    app = _make_app(bridge)
    with TestClient(app) as client:
        r = client.post("/camera_pan/cmd", json={"pan": 95.0})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert bridge.pan_calls == [95.0]
    assert bridge.tilt_calls == []


def test_post_cmd_tilt_only_calls_publish_tilt() -> None:
    bridge = _mock_bridge()
    app = _make_app(bridge)
    with TestClient(app) as client:
        r = client.post("/camera_pan/cmd", json={"tilt": 60.0})
    assert r.status_code == 200
    assert bridge.tilt_calls == [60.0]
    assert bridge.pan_calls == []


def test_post_cmd_both_axes() -> None:
    bridge = _mock_bridge()
    app = _make_app(bridge)
    with TestClient(app) as client:
        r = client.post("/camera_pan/cmd", json={"pan": 80.0, "tilt": 100.0})
    assert r.status_code == 200
    assert bridge.pan_calls == [80.0]
    assert bridge.tilt_calls == [100.0]


def test_post_cmd_neither_axis_rejected() -> None:
    bridge = _mock_bridge()
    app = _make_app(bridge)
    with TestClient(app) as client:
        r = client.post("/camera_pan/cmd", json={})
    assert r.status_code == 422  # pydantic validation error


# ── GET /camera_pan/health ──────────────────────────────────────────────────


def test_health_returns_required_keys(monkeypatch) -> None:
    monkeypatch.setenv("ROS_DOMAIN_ID", "207")
    bridge = _mock_bridge()
    bridge.health.return_value = {
        "ros_domain_id": 207,
        "ros_ok": True,
        "last_state_age_ms": 12,
    }
    app = _make_app(bridge)
    with TestClient(app) as client:
        r = client.get("/camera_pan/health")
    assert r.status_code == 200
    body = r.json()
    for k in ("ros_domain_id", "ros_ok", "last_state_age_ms"):
        assert k in body
    assert body["ros_domain_id"] == 207


# ── WS /camera_pan/state ────────────────────────────────────────────────────


def test_ws_state_emits_snapshot() -> None:
    bridge = _mock_bridge()
    app = _make_app(bridge)
    with TestClient(app) as client:
        with client.websocket_connect("/camera_pan/state") as ws:
            msg = ws.receive_json()
    for k in ("pan_deg", "tilt_deg", "age_ms", "ros_ok", "ts_ms"):
        assert k in msg
    assert msg["pan_deg"] == 90.0
    assert msg["tilt_deg"] == 90.0


def test_ws_state_emits_at_10hz() -> None:
    bridge = _mock_bridge()
    app = _make_app(bridge)
    samples: list[float] = []
    with TestClient(app) as client:
        with client.websocket_connect("/camera_pan/state") as ws:
            t0 = time.monotonic()
            for _ in range(8):
                ws.receive_json()
                samples.append(time.monotonic() - t0)
    # 0.8s 안에 8개 → ~10Hz. 여유있게 6~10
    assert 6 <= len(samples) <= 10, f"got {len(samples)} in {samples[-1]:.2f}s"


# ── 토픽 이름 ────────────────────────────────────────────────────────────────


def test_topic_names_match_servo_bridge() -> None:
    assert TOPIC_CMD_PAN == "/servo_bridge/cmd_pan"
    assert TOPIC_CMD_TILT == "/servo_bridge/cmd_tilt"
    assert TOPIC_STATE == "/servo_bridge/state"
    assert PAN_JOINT == "camera_pan_joint"
    assert TILT_JOINT == "camera_tilt_joint"


# ── Hub queue 드롭 정책 (teleop 패턴 따름) ─────────────────────────────────


def test_queue_drops_oldest_when_full() -> None:
    bridge = _mock_bridge()
    hub = router_mod._Hub(bridge)
    q = hub._add_client()

    async def _run() -> list[int]:
        await q.put({"id": 1})
        await q.put({"id": 2})
        if q.full():
            q.get_nowait()
        await q.put({"id": 3})
        return [(await q.get())["id"], (await q.get())["id"]]

    ids = asyncio.new_event_loop().run_until_complete(_run())
    assert ids == [2, 3]
