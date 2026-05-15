"""비밀번호 변경 테스트 — current_password 검증."""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_password_change_with_valid_current_password_succeeds(
    teacher_client: AsyncClient,
):
    response = await teacher_client.patch(
        "/api/users/me",
        json={"current_password": "test1234", "password": "newpassword1"},
    )
    assert response.status_code == 200

    # 새 비밀번호로 로그인 가능
    logout = await teacher_client.post("/api/auth/cookie/logout")
    assert logout.status_code == 204

    login = await teacher_client.post(
        "/api/auth/cookie/login",
        data={"username": "teacher@test.com", "password": "newpassword1"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login.status_code == 204


async def test_password_change_with_wrong_current_returns_400(
    teacher_client: AsyncClient,
):
    response = await teacher_client.patch(
        "/api/users/me",
        json={"current_password": "wrongpw", "password": "newpassword1"},
    )
    assert response.status_code == 400


async def test_password_change_without_current_returns_400(
    teacher_client: AsyncClient,
):
    response = await teacher_client.patch(
        "/api/users/me",
        json={"password": "newpassword1"},
    )
    assert response.status_code == 400


async def test_password_too_short_returns_400(teacher_client: AsyncClient):
    response = await teacher_client.patch(
        "/api/users/me",
        json={"current_password": "test1234", "password": "short"},
    )
    assert response.status_code == 400


async def test_name_only_update_does_not_require_current_password(
    teacher_client: AsyncClient,
):
    response = await teacher_client.patch(
        "/api/users/me",
        json={"name": "새이름"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "새이름"
