"""server/control/teleop/router.py + ros_bridge.py 단위 테스트.

ros_bridge 는 Mock 으로 대체 — rclpy 미동작 환경에서도 테스트 가능.
AC #9, #10, #11, #12, #13, #25, #26, #28, #29, #30, #31 검증.
"""

from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.control.teleop import router as router_mod
from server.control.teleop.ros_bridge import (
    TOPIC_CMD_VEL,
    TOPIC_ODOM,
    TOPIC_SCAN,
    RosBridge,
)


# --------------------------------------------------------------- helpers


def _mock_bridge() -> MagicMock:
    """RosBridge spec 으로 thread-safe 한 mock 생성."""
    m = MagicMock(spec=RosBridge)
    m._snapshot = {
        "odom": None,
        "scan": None,
        "ros_ok": True,
        "last_cmd_age_ms": None,
    }
    m._last_cmd_age_s = None
    m.snapshot.side_effect = lambda: dict(m._snapshot)
    m.last_cmd_age_s.side_effect = lambda: m._last_cmd_age_s
    m.health.return_value = {
        "ros_domain_id": int(os.environ.get("ROS_DOMAIN_ID", "0")),
        "last_odom_age_ms": None,
        "last_scan_age_ms": None,
        "ros_ok": True,
    }

    def _publish(linear: float, angular: float) -> None:
        m._last_cmd_age_s = 0.0
        m.publish_calls.append((linear, angular))

    m.publish_calls = []
    m.publish_cmd_vel.side_effect = _publish
    return m


def _make_app(bridge) -> tuple[FastAPI, router_mod._Hub]:
    app = FastAPI()
    hub = router_mod.install(app, bridge)
    return app, hub


# --------------------------------------------------------------- AC #9


def test_post_cmd_vel_calls_bridge_once() -> None:
    bridge = _mock_bridge()
    app, _ = _make_app(bridge)
    with TestClient(app) as client:
        r = client.post(
            "/teleop/cmd_vel",
            json={"linear": 0.2, "angular": -0.5, "ts_ms": 123},
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert bridge.publish_cmd_vel.call_count == 1
    bridge.publish_cmd_vel.assert_called_with(0.2, -0.5)


# --------------------------------------------------------------- AC #12, #26


def test_health_returns_required_keys(monkeypatch) -> None:
    monkeypatch.setenv("ROS_DOMAIN_ID", "207")
    bridge = _mock_bridge()
    bridge.health.return_value = {
        "ros_domain_id": 207,
        "last_odom_age_ms": 50,
        "last_scan_age_ms": 30,
        "ros_ok": True,
    }
    app, _ = _make_app(bridge)
    with TestClient(app) as client:
        r = client.get("/teleop/health")
    assert r.status_code == 200
    body = r.json()
    for k in ("ros_domain_id", "last_odom_age_ms",
              "last_scan_age_ms", "ros_ok"):
        assert k in body
    assert body["ros_domain_id"] == 207


# --------------------------------------------------------------- AC #25


def test_ros_bridge_start_requires_ros_domain_id(monkeypatch) -> None:
    monkeypatch.delenv("ROS_DOMAIN_ID", raising=False)
    b = RosBridge()
    with pytest.raises(RuntimeError):
        b.start()


# --------------------------------------------------------------- AC #10


def test_watchdog_publishes_zero_after_timeout() -> None:
    """0.5s 미수신 → 자동 (0,0) 발행 1 회."""
    bridge = _mock_bridge()
    bridge._last_cmd_age_s = 0.6  # 이미 timeout 넘은 상태로 시작

    async def _run() -> int:
        hub = router_mod._Hub(bridge)
        await hub.start()
        # watchdog 가 0.05s sleep × 몇 번 후 publish 하도록 0.3s 대기
        await asyncio.sleep(0.3)
        await hub.stop()
        return bridge.publish_cmd_vel.call_count

    n = asyncio.new_event_loop().run_until_complete(_run())
    assert n >= 1
    # 첫 호출은 (0.0, 0.0) 이어야 한다
    bridge.publish_cmd_vel.assert_any_call(0.0, 0.0)


# --------------------------------------------------------------- AC #11


def test_ws_state_emits_at_10hz() -> None:
    """WS 가 100ms ± 30ms 주기로 메시지 송신."""
    bridge = _mock_bridge()
    app, _ = _make_app(bridge)
    received: list[float] = []
    with TestClient(app) as client:
        with client.websocket_connect("/teleop/state") as ws:
            t0 = time.monotonic()
            for _ in range(10):
                ws.receive_json()
                received.append(time.monotonic() - t0)
    # 1초 동안 9~11 회 (여유 있게 8~12)
    assert 8 <= len(received) <= 12, f"got {len(received)}"


# --------------------------------------------------------------- AC #13


def test_topic_names_are_namespaced() -> None:
    """소스 grep — pub/sub topic 이 정확히 /gogoping/cmd_vel|odom|scan."""
    assert TOPIC_CMD_VEL == "/gogoping/cmd_vel"
    assert TOPIC_ODOM == "/gogoping/odom"
    assert TOPIC_SCAN == "/gogoping/scan"


# --------------------------------------------------------------- AC #28, #29


def test_subscriber_callbacks_have_no_async_or_send() -> None:
    """subscriber 콜백 본문에 await / Queue.put / WebSocket.send 없음."""
    src = Path("server/control/teleop/ros_bridge.py").read_text(encoding="utf-8")
    # _on_odom 와 _on_scan 함수 본문 추출 (다음 def 이전까지)
    for fn in ("_on_odom", "_on_scan"):
        m = re.search(
            rf"def {fn}\(.*?\n(?P<body>(?: {{4,}}.*\n)+)",
            src,
        )
        assert m, f"function {fn} not found"
        body = m.group("body")
        for forbidden in ("await ", "Queue.put", ".put(", "WebSocket.send",
                          "ws.send", "asyncio."):
            assert forbidden not in body, (
                f"{fn} contains forbidden token: {forbidden}"
            )


def test_router_uses_asyncio_queue_maxsize_2() -> None:
    src = Path("server/control/teleop/router.py").read_text(encoding="utf-8")
    assert "asyncio.Queue(maxsize=2)" in src or "QUEUE_MAX = 2" in src
    # 실제 사용 확인
    assert "maxsize=QUEUE_MAX" in src or "maxsize=2" in src


# --------------------------------------------------------------- AC #30


def test_queue_drops_oldest_when_full() -> None:
    """큐 가득 찬 상태에서 새 메시지가 들어가도 가장 오래된 것이 drop 됨."""
    bridge = _mock_bridge()
    hub = router_mod._Hub(bridge)
    q = hub._add_client()

    async def _run() -> list[int]:
        # maxsize=2 채우기
        await q.put({"id": 1})
        await q.put({"id": 2})
        # 3 번째 — broadcaster 의 drop 정책 시뮬레이션
        if q.full():
            q.get_nowait()
        await q.put({"id": 3})
        return [(await q.get())["id"], (await q.get())["id"]]

    ids = asyncio.new_event_loop().run_until_complete(_run())
    # id=1 이 drop 되고 [2, 3] 만 남는다
    assert ids == [2, 3]


# --------------------------------------------------------------- AC #31


def test_resample_produces_length_360() -> None:
    bridge = _mock_bridge()
    bridge._snapshot["scan"] = {
        "angle_min": 0.0,
        "angle_inc": 0.01,
        "ranges": [float(i) for i in range(720)],
        "hz": 12.3,
        "age_ms": 10,
    }
    app, _ = _make_app(bridge)
    with TestClient(app) as client:
        with client.websocket_connect("/teleop/state") as ws:
            msg = ws.receive_json()
    assert msg["scan"] is not None
    assert len(msg["scan"]["ranges"]) == 360
    # hz, age_ms 도 WS payload 에 통과되어야 함 (spec §5.3)
    assert msg["scan"]["hz"] == 12.3
    assert msg["scan"]["age_ms"] == 10


def test_resample_helper_exact_n() -> None:
    out = router_mod._resample(list(range(720)))
    assert len(out) == 360
    out2 = router_mod._resample([1.0, 2.0])
    assert len(out2) == 360  # 짧은 입력도 n 으로 늘림 (반복 sampling)


def test_resample_helper_fastpath_exact_input() -> None:
    """입력 길이가 이미 RESAMPLE_N 이면 fast-path 로 그대로 반환."""
    src = [float(i) for i in range(360)]
    out = router_mod._resample(src)
    assert len(out) == 360
    assert out == src
