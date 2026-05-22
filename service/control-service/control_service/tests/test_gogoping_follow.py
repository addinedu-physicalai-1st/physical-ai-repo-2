"""POST /api/gogoping/follow/{start,stop} + GET /state — backend lookup 경로."""
import uuid as _uuid
import pytest
from httpx import AsyncClient
from fastapi_users.password import PasswordHelper


@pytest.mark.asyncio
async def test_follow_start_lookups_embedding_and_publishes(
    teacher_client: AsyncClient, db_session, monkeypatch
):
    from control_service.routers import gogoping_follow as router_mod
    from control_db.models import TeacherFaceEmbedding, User

    helper = PasswordHelper()
    tid = _uuid.uuid4()
    db_session.add(User(
        id=tid, email="t_c2@x.com", hashed_password=helper.hash("p"),
        is_active=True, is_verified=True, is_superuser=False,
        role="teacher", name="C2교사",
    ))
    await db_session.flush()  # User must exist before FK'd embedding
    db_session.add(TeacherFaceEmbedding(teacher_id=tid, embedding=[0.1] * 512))
    await db_session.flush()

    sent = []
    monkeypatch.setattr(router_mod, "publish_follow_target", lambda p: sent.append(p))

    res = await teacher_client.post(
        "/api/gogoping/follow/start", json={"teacher_id": str(tid)}
    )
    assert res.status_code == 200, res.text
    assert len(sent) == 1
    assert sent[0]["teacher_id"] == str(tid)
    assert len(sent[0]["embedding"]) == 512


@pytest.mark.asyncio
async def test_follow_start_404_unknown_teacher(teacher_client: AsyncClient, monkeypatch):
    from control_service.routers import gogoping_follow as router_mod
    monkeypatch.setattr(router_mod, "publish_follow_target", lambda p: None)
    res = await teacher_client.post(
        "/api/gogoping/follow/start",
        json={"teacher_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_follow_start_409_no_embedding(teacher_client: AsyncClient, db_session, monkeypatch):
    from control_db.models import User
    from control_service.routers import gogoping_follow as router_mod
    monkeypatch.setattr(router_mod, "publish_follow_target", lambda p: None)
    helper = PasswordHelper()
    tid = _uuid.uuid4()
    db_session.add(User(
        id=tid, email="t_noface@x.com", hashed_password=helper.hash("p"),
        is_active=True, is_verified=True, is_superuser=False,
        role="teacher", name="얼굴없음",
    ))
    await db_session.flush()
    res = await teacher_client.post(
        "/api/gogoping/follow/start", json={"teacher_id": str(tid)}
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_follow_stop_signals_ros(teacher_client: AsyncClient, monkeypatch):
    from control_service.routers import gogoping_follow as router_mod
    stops = []
    monkeypatch.setattr(router_mod, "publish_follow_stop", lambda: stops.append(1))
    res = await teacher_client.post("/api/gogoping/follow/stop", json={})
    assert res.status_code == 200
    assert len(stops) == 1


@pytest.mark.asyncio
async def test_follow_state_default(teacher_client: AsyncClient, monkeypatch):
    from control_service.routers import gogoping_follow as router_mod
    monkeypatch.setattr(router_mod, "current_tracking_state", lambda: None)
    res = await teacher_client.get("/api/gogoping/follow/state")
    body = res.json()
    assert body["active"] is False
