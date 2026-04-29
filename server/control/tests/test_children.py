"""자녀 CRUD 테스트."""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_create_child_as_teacher_returns_201(teacher_client: AsyncClient):
    response = await teacher_client.post(
        "/api/children",
        json={"name": "김민준", "birth_date": "2021-03-12", "class_name": "햇살반"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "김민준"
    assert body["class_name"] == "햇살반"
    assert "id" in body


async def test_create_child_as_parent_returns_403(parent_client: AsyncClient):
    response = await parent_client.post(
        "/api/children",
        json={"name": "X", "birth_date": "2021-01-01", "class_name": "Y"},
    )
    assert response.status_code == 403


async def test_list_children_returns_sorted(teacher_client: AsyncClient):
    await teacher_client.post(
        "/api/children",
        json={"name": "박서윤", "birth_date": "2021-05-04", "class_name": "햇살반"},
    )
    await teacher_client.post(
        "/api/children",
        json={"name": "김민준", "birth_date": "2021-03-12", "class_name": "햇살반"},
    )
    response = await teacher_client.get("/api/children")
    assert response.status_code == 200
    names = [c["name"] for c in response.json()]
    assert names == ["김민준", "박서윤"]   # 가나다순


async def test_get_child_includes_parents(teacher_client: AsyncClient):
    create = await teacher_client.post(
        "/api/children",
        json={"name": "최아인", "birth_date": "2021-02-15", "class_name": "꽃잎반"},
    )
    cid = create.json()["id"]
    response = await teacher_client.get(f"/api/children/{cid}")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "최아인"
    assert body["parents"] == []   # 아직 학부모 매핑 없음


async def test_get_nonexistent_child_returns_404(teacher_client: AsyncClient):
    response = await teacher_client.get("/api/children/99999")
    assert response.status_code == 404


async def test_my_children_for_parent_returns_only_mapped(
    client: AsyncClient, make_user, db_session
):
    from server.db.models import Child, ParentChild
    from datetime import date, datetime, timezone

    parent = await make_user("p@x.com", "test1234", role="parent")

    # 자녀 2명 생성, 1명만 parent 매핑
    c1 = Child(name="A", birth_date=date(2021, 1, 1), class_name="햇살반",
               photo_url=None, created_at=datetime.now(timezone.utc))
    c2 = Child(name="B", birth_date=date(2021, 2, 2), class_name="햇살반",
               photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add_all([c1, c2])
    await db_session.flush()
    db_session.add(ParentChild(parent_id=parent.id, child_id=c1.id))
    await db_session.flush()

    # parent 로 로그인
    login = await client.post(
        "/api/auth/cookie/login",
        data={"username": "p@x.com", "password": "test1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert login.status_code == 204

    response = await client.get("/api/parent/children")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "A"


async def test_my_children_as_teacher_returns_403(teacher_client: AsyncClient):
    response = await teacher_client.get("/api/parent/children")
    assert response.status_code == 403
