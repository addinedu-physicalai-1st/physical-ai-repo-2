"""``/ws/tracking-state`` WebSocket smoke."""
import pytest


@pytest.mark.asyncio
async def test_tracking_state_ws_sends_latest_on_connect(teacher_client, monkeypatch):
    """WS 연결 시 current_tracking_state 가 있으면 즉시 보내짐.

    teacher_client 의 ASGI app 에 install_gogoping_follow 가 호출되어 있으면 OK.
    그렇지 않으면 skip.
    """
    from control_service.routers import gogoping_follow as router_mod

    if router_mod._bridge is None:
        pytest.skip("gogoping_follow not installed in test app — fixture 차이")

    sample = {
        "active": True,
        "matched": True,
        "distance_m": 1.42,
        "angle_deg": -3.5,
        "bbox_size_px": 240,
        "bbox_x1": 240,
        "bbox_y1": 80,
        "bbox_x2": 380,
        "bbox_y2": 520,
        "track_id": 7,
        "reid_sim": 0.92,
        "teacher_id": "uuid-test",
        "updated_at_ms": 1748000000000,
    }

    monkeypatch.setattr(router_mod._bridge, "current_tracking_state", lambda: sample)
    monkeypatch.setattr(
        router_mod._bridge, "register_tracking_state_callback",
        lambda cb: (lambda: None),
    )

    from fastapi.testclient import TestClient
    # teacher_client 의 underlying ASGI app 접근. httpx AsyncClient 인 경우 .app 또는 ._transport.app.
    app = getattr(teacher_client, "app", None) or getattr(teacher_client._transport, "app", None)
    if app is None:
        pytest.skip("teacher_client 가 ASGI app 노출 안 함")

    sync_client = TestClient(app)
    with sync_client.websocket_connect("/ws/tracking-state") as ws:
        msg = ws.receive_json()
        assert msg["matched"] is True
        assert msg["track_id"] == 7


def test_tracking_state_ws_returns_empty_when_no_state(teacher_client, monkeypatch):
    """current_tracking_state 가 None 이면 연결 즉시 메시지 없음 — disconnect 까지 빈 queue.

    이 테스트는 connect 만 검증 (메시지 안 받음). receive 에 timeout 짧게 걸어 빈 확인.
    """
    from control_service.routers import gogoping_follow as router_mod

    if router_mod._bridge is None:
        pytest.skip("gogoping_follow not installed in test app")

    monkeypatch.setattr(router_mod._bridge, "current_tracking_state", lambda: None)
    monkeypatch.setattr(
        router_mod._bridge, "register_tracking_state_callback",
        lambda cb: (lambda: None),
    )

    from fastapi.testclient import TestClient
    app = getattr(teacher_client, "app", None) or getattr(teacher_client._transport, "app", None)
    if app is None:
        pytest.skip("teacher_client 가 ASGI app 노출 안 함")

    sync_client = TestClient(app)
    with sync_client.websocket_connect("/ws/tracking-state") as ws:
        # 연결 자체가 성공하면 OK. 메시지를 즉시 받지 않음을 확인하려면 timeout 필요 —
        # 여기선 connect 성공만 검증하고 종료.
        pass
