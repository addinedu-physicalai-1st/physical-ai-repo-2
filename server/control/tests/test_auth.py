"""인증 흐름 검증 — login → /users/me → logout."""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_users_me_unauthenticated_returns_401(client: AsyncClient):
    response = await client.get("/api/users/me")
    assert response.status_code == 401


async def test_login_success_returns_204_and_sets_cookie(client, make_user):
    await make_user("a@b", "test1234", role="teacher")
    response = await client.post(
        "/api/auth/cookie/login",
        data={"username": "a@b", "password": "test1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 204
    assert "session" in response.cookies


async def test_login_wrong_password_returns_400(client, make_user):
    await make_user("a@b", "test1234")
    response = await client.post(
        "/api/auth/cookie/login",
        data={"username": "a@b", "password": "wrong"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 400


async def test_users_me_returns_user_info_after_login(teacher_client: AsyncClient):
    response = await teacher_client.get("/api/users/me")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "teacher@test.com"
    assert body["role"] == "teacher"
    assert body["name"] == "김선생"


async def test_logout_clears_session(teacher_client: AsyncClient):
    response = await teacher_client.post("/api/auth/cookie/logout")
    assert response.status_code == 204

    me = await teacher_client.get("/api/users/me")
    assert me.status_code == 401
