"""학부모 생성 + 발급된 비밀번호로 로그인 검증."""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_create_parent_returns_initial_password(teacher_client: AsyncClient):
    child = await teacher_client.post(
        "/api/children",
        json={"name": "민준", "birth_date": "2021-03-12", "class_name": "햇살반"},
    )
    cid = child.json()["id"]

    response = await teacher_client.post(
        "/api/parents",
        json={
            "name": "김은혜",
            "email": "mom@example.com",
            "phone": "010-1234-5678",
            "child_id": cid,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["parent"]["email"] == "mom@example.com"
    assert body["parent"]["name"] == "김은혜"
    assert body["parent"]["phone"] == "010-1234-5678"
    assert cid in body["parent"]["child_ids"]
    assert body["initial_password"] == "1234"


async def test_created_parent_can_login_with_initial_password(
    client: AsyncClient, teacher_client: AsyncClient
):
    child = await teacher_client.post(
        "/api/children",
        json={"name": "도윤", "birth_date": "2021-07-21", "class_name": "햇살반"},
    )
    cid = child.json()["id"]

    create = await teacher_client.post(
        "/api/parents",
        json={
            "name": "박지민", "email": "p2@x.com", "phone": "010-0000-0000",
            "child_id": cid,
        },
    )
    initial = create.json()["initial_password"]

    # 새 client (쿠키 깨끗) 로 로그인 — 같은 db_session 공유
    login = await client.post(
        "/api/auth/cookie/login",
        data={"username": "p2@x.com", "password": initial},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login.status_code == 204


async def test_create_parent_with_nonexistent_child_returns_404(
    teacher_client: AsyncClient,
):
    response = await teacher_client.post(
        "/api/parents",
        json={
            "name": "X", "email": "x@x.com", "phone": "010", "child_id": 99999,
        },
    )
    assert response.status_code == 404


async def test_create_parent_as_parent_returns_403(parent_client: AsyncClient):
    response = await parent_client.post(
        "/api/parents",
        json={"name": "X", "email": "x@x.com", "phone": "010", "child_id": 1},
    )
    assert response.status_code == 403
