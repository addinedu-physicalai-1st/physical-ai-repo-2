"""server/control/streaming/ws_router.py 통합 테스트.

PLAN §3.1, §3.3, §3.4, §5.3, SR-CAM-002, SR-CAM-003.

FastAPI TestClient.websocket_connect 로 핸드셰이크/메시지 흐름 검증.
auth 는 dev 모드 (require_auth=False) 가정 — 자동 anonymous 통과.
"""

from __future__ import annotations

import json
import struct
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.control.streaming import config as scfg
from server.control.streaming.client_registry import ClientRegistry
from server.control.streaming.frame_hub import FrameHub
from server.control.streaming.protocol import (
    VideoPacket,
    WS_FRAME_HEADER_FMT,
    WS_FRAME_HEADER_SIZE,
    WS_MSG_VIDEO_FRAME,
)
from server.control.streaming.ws_router import make_ws_router


# 모든 테스트에서 dev 모드 (auth bypass)
@pytest.fixture(autouse=True)
def _dev_auth(monkeypatch) -> None:
    monkeypatch.setattr(scfg.settings, "require_auth", False)


@pytest.fixture
def hub() -> FrameHub:
    return FrameHub()


@pytest.fixture
def registry() -> ClientRegistry:
    return ClientRegistry()


@pytest.fixture
def app(hub: FrameHub, registry: ClientRegistry) -> FastAPI:
    a = FastAPI()
    a.include_router(make_ws_router(registry, hub))
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _hello(client_id: str = "test-client", kind: str = "admin") -> dict:
    return {
        "type": "hello",
        "client_id": client_id,
        "client_kind": kind,
        "ts_ms": int(time.time() * 1000),
    }


def _subscribe(robot: str = "gogoping", stream: int = 0) -> dict:
    return {
        "type": "subscribe", "robot": robot, "stream": stream,
        "ts_ms": int(time.time() * 1000),
    }


def _unsubscribe(robot: str = "gogoping", stream: int = 0) -> dict:
    return {
        "type": "unsubscribe", "robot": robot, "stream": stream,
        "ts_ms": int(time.time() * 1000),
    }


# --------------------------------------------------------- handshake


def test_welcome_then_hello_ack(client: TestClient) -> None:
    with client.websocket_connect("/ws/video-stream") as ws:
        welcome = ws.receive_json()
        assert welcome["type"] == "welcome"
        assert "ts_ms" in welcome

        ws.send_json(_hello())
        ack = ws.receive_json()
        assert ack["type"] == "hello_ack"
        assert ack["client_id"] == "test-client"
        assert "gogoping" in ack["active_robots"]


def test_invalid_hello_closes(client: TestClient) -> None:
    with client.websocket_connect("/ws/video-stream") as ws:
        ws.receive_json()   # welcome
        ws.send_json({"type": "garbage"})
        # 서버가 error + close 보냄
        msg = ws.receive_json()
        assert msg["type"] == "error"
        # 다음 receive 는 close → WebSocketDisconnect
        with pytest.raises(Exception):
            ws.receive_text()


# --------------------------------------------------------- subscribe/unsubscribe


def test_subscribe_roundtrip(
    client: TestClient, hub: FrameHub, registry: ClientRegistry,
) -> None:
    with client.websocket_connect("/ws/video-stream") as ws:
        ws.receive_json()   # welcome
        ws.send_json(_hello("c1"))
        ws.receive_json()   # hello_ack

        ws.send_json(_subscribe("gogoping", 0))
        ack = ws.receive_json()
        assert ack["type"] == "subscribed"
        assert ack["robot"] == "gogoping"
        assert ack["stream"] == 0

        # registry 에 client 등록됨
        assert registry.count() == 1
        # hub 에 (1, 0) 구독 등록됨
        assert hub.subscriber_count(1, 0) == 1

        ws.send_json(_unsubscribe("gogoping", 0))
        ack = ws.receive_json()
        assert ack["type"] == "unsubscribed"
        assert hub.subscriber_count(1, 0) == 0


def test_subscribe_then_publish_delivers_binary_frame(
    client: TestClient, hub: FrameHub,
) -> None:
    with client.websocket_connect("/ws/video-stream") as ws:
        ws.receive_json()   # welcome
        ws.send_json(_hello("c1"))
        ws.receive_json()   # hello_ack

        ws.send_json(_subscribe("gogoping", 0))
        ws.receive_json()   # subscribed ack

        # 서버가 frame_hub.publish 받으면 client 에 binary 전달
        packet = VideoPacket(
            robot_id=1, stream_id=0, frame_seq=42,
            ts_ms=1234567890, jpeg=b"jpeg-bytes",
        )
        hub.publish(packet)

        data = ws.receive_bytes()
        assert len(data) >= WS_FRAME_HEADER_SIZE
        msg_type, robot_id, stream_id = data[0], data[1], data[2]
        assert msg_type == WS_MSG_VIDEO_FRAME
        assert robot_id == 1
        assert stream_id == 0
        # jpeg payload 확인
        size = struct.unpack("!I", data[16:20])[0]
        assert data[WS_FRAME_HEADER_SIZE:WS_FRAME_HEADER_SIZE + size] == b"jpeg-bytes"


def test_unsubscribe_stops_delivery(client: TestClient, hub: FrameHub) -> None:
    with client.websocket_connect("/ws/video-stream") as ws:
        ws.receive_json()
        ws.send_json(_hello())
        ws.receive_json()
        ws.send_json(_subscribe("gogoping", 0))
        ws.receive_json()

        hub.publish(VideoPacket(1, 0, 1, 0, b"a"))
        ws.receive_bytes()   # 1번째 frame 도착

        ws.send_json(_unsubscribe("gogoping", 0))
        ws.receive_json()   # unsubscribed ack

        # 이후 publish 는 도착 안 함 — 짧은 timeout 으로 검증
        hub.publish(VideoPacket(1, 0, 2, 0, b"b"))
        # WebSocket TestClient 는 timeout 옵션이 없어서, 다음 메시지 안 오는지 short-poll 로 확인
        # 대신 unsub 효과는 hub.subscriber_count 로 검증
        assert hub.subscriber_count(1, 0) == 0


def test_invalid_subscribe_returns_error(client: TestClient) -> None:
    with client.websocket_connect("/ws/video-stream") as ws:
        ws.receive_json()
        ws.send_json(_hello())
        ws.receive_json()

        ws.send_json({"type": "subscribe", "robot": "not-a-robot", "ts_ms": 1})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert msg["code"] == "invalid_message"


def test_unknown_message_type_returns_error(client: TestClient) -> None:
    with client.websocket_connect("/ws/video-stream") as ws:
        ws.receive_json()
        ws.send_json(_hello())
        ws.receive_json()

        ws.send_json({"type": "unknown", "ts_ms": 1})
        msg = ws.receive_json()
        assert msg["type"] == "error"


# --------------------------------------------------------- multi-subscribe (시나리오 B)


def test_one_client_multi_robot(client: TestClient, hub: FrameHub) -> None:
    """SR-CAM-003: 한 client 가 여러 로봇 동시 구독."""
    with client.websocket_connect("/ws/video-stream") as ws:
        ws.receive_json()
        ws.send_json(_hello())
        ws.receive_json()

        ws.send_json(_subscribe("gogoping", 0))
        ws.receive_json()
        ws.send_json(_subscribe("eduping", 0))
        ws.receive_json()

        assert hub.subscriber_count(1, 0) == 1
        assert hub.subscriber_count(2, 0) == 1

        # 두 로봇 영상 모두 수신
        hub.publish(VideoPacket(1, 0, 1, 0, b"gogo"))
        hub.publish(VideoPacket(2, 0, 1, 0, b"edu "))

        f1 = ws.receive_bytes()
        f2 = ws.receive_bytes()
        # 순서는 무관, robot_id 로 구분
        rids = sorted([f1[1], f2[1]])
        assert rids == [1, 2]


# --------------------------------------------------------- disconnect cleanup


def test_disconnect_cleans_subscriptions(
    client: TestClient, hub: FrameHub, registry: ClientRegistry,
) -> None:
    with client.websocket_connect("/ws/video-stream") as ws:
        ws.receive_json()
        ws.send_json(_hello("c1"))
        ws.receive_json()
        ws.send_json(_subscribe("gogoping", 0))
        ws.receive_json()
        assert hub.subscriber_count(1, 0) == 1
        assert registry.count() == 1
    # WS context 빠져나옴 → cleanup
    # 서버 측 cleanup 은 비동기라 약간 대기
    time.sleep(0.1)
    assert hub.subscriber_count(1, 0) == 0
    assert registry.count() == 0


# --------------------------------------------------------- 같은 client_id 재연결


def test_reconnect_with_same_client_id_replaces_old(
    client: TestClient, hub: FrameHub, registry: ClientRegistry,
) -> None:
    """동일 client_id 두 번째 연결 시 이전 연결을 닫고 새 연결로 교체."""
    ws1 = client.websocket_connect("/ws/video-stream").__enter__()
    try:
        ws1.receive_json()
        ws1.send_json(_hello("same-id"))
        ws1.receive_json()
        ws1.send_json(_subscribe("gogoping", 0))
        ws1.receive_json()
        assert registry.count() == 1

        # 두 번째 연결 (같은 client_id)
        with client.websocket_connect("/ws/video-stream") as ws2:
            ws2.receive_json()
            ws2.send_json(_hello("same-id"))
            ws2.receive_json()
            # registry 에 1개만 남아있어야 (이전 ws1 의 항목은 교체됨)
            time.sleep(0.05)
            assert registry.count() == 1
    finally:
        try:
            ws1.__exit__(None, None, None)
        except Exception:
            pass
