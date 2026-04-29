"""사진 endpoint 테스트."""
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_my_child_photos_returns_subject_matched(
    client: AsyncClient, make_user, db_session
):
    from server.db.models import Child, ParentChild, Photo, PhotoSubject

    parent = await make_user("p@x.com", "test1234", role="parent")
    child = Child(name="A", birth_date=date(2021, 1, 1), class_name="햇살반",
                  photo_url=None, created_at=datetime.now(timezone.utc))
    other = Child(name="X", birth_date=date(2021, 2, 2), class_name="햇살반",
                  photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add_all([child, other])
    await db_session.flush()
    db_session.add(ParentChild(parent_id=parent.id, child_id=child.id))

    p1 = Photo(child_id=child.id, url="https://picsum.photos/seed/1/400",
               taken_at=datetime.now(timezone.utc), emotion="happy", mode="율동")
    p2 = Photo(child_id=other.id, url="https://picsum.photos/seed/2/400",
               taken_at=datetime.now(timezone.utc), emotion="happy", mode="율동")
    db_session.add_all([p1, p2])
    await db_session.flush()

    db_session.add(PhotoSubject(photo_id=p1.id, child_id=child.id))
    db_session.add(PhotoSubject(photo_id=p2.id, child_id=other.id))
    await db_session.flush()

    await client.post(
        "/api/auth/cookie/login",
        data={"username": "p@x.com", "password": "test1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    response = await client.get(f"/api/children/{child.id}/photos")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["url"].endswith("/1/400")


async def test_other_childs_photos_returns_404(
    client: AsyncClient, make_user, db_session
):
    from server.db.models import Child

    parent = await make_user("p@x.com", "test1234", role="parent")
    other = Child(name="X", birth_date=date(2021, 1, 1), class_name="햇살반",
                  photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add(other)
    await db_session.flush()

    await client.post(
        "/api/auth/cookie/login",
        data={"username": "p@x.com", "password": "test1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response = await client.get(f"/api/children/{other.id}/photos")
    assert response.status_code == 404
