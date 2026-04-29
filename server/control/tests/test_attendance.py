"""출결 endpoint 테스트."""
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_list_all_attendance_includes_unchecked_children(
    teacher_client: AsyncClient, db_session
):
    from server.db.models import Attendance, Child

    today = date.today()
    c1 = Child(name="A", birth_date=date(2021, 1, 1), class_name="햇살반",
               photo_url=None, created_at=datetime.now(timezone.utc))
    c2 = Child(name="B", birth_date=date(2021, 2, 2), class_name="햇살반",
               photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add_all([c1, c2])
    await db_session.flush()

    db_session.add(
        Attendance(
            child_id=c1.id, date=today, type="IN",
            time=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc),
        )
    )
    await db_session.flush()

    response = await teacher_client.get(f"/api/attendance?date={today.isoformat()}")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2

    by_name = {r["child_name"]: r for r in body}
    assert by_name["A"]["check_in"] is not None
    assert by_name["A"]["check_out"] is None
    assert by_name["B"]["check_in"] is None


async def test_list_all_attendance_as_parent_returns_403(parent_client: AsyncClient):
    response = await parent_client.get(f"/api/attendance?date={date.today().isoformat()}")
    assert response.status_code == 403


async def test_child_attendance_for_my_child_works(
    client: AsyncClient, make_user, db_session
):
    from server.db.models import Attendance, Child, ParentChild

    parent = await make_user("p@x.com", "test1234", role="parent")
    today = date.today()
    child = Child(name="민준", birth_date=date(2021, 1, 1), class_name="햇살반",
                  photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add(child)
    await db_session.flush()
    db_session.add(ParentChild(parent_id=parent.id, child_id=child.id))
    db_session.add(
        Attendance(child_id=child.id, date=today, type="IN",
                   time=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc))
    )
    await db_session.flush()

    await client.post(
        "/api/auth/cookie/login",
        data={"username": "p@x.com", "password": "test1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response = await client.get(f"/api/children/{child.id}/attendance")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1


async def test_child_attendance_for_others_child_returns_404(
    client: AsyncClient, make_user, db_session
):
    from server.db.models import Child

    parent = await make_user("p@x.com", "test1234", role="parent")
    other_child = Child(name="X", birth_date=date(2021, 1, 1), class_name="햇살반",
                        photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add(other_child)
    await db_session.flush()

    await client.post(
        "/api/auth/cookie/login",
        data={"username": "p@x.com", "password": "test1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    response = await client.get(f"/api/children/{other_child.id}/attendance")
    assert response.status_code == 404
