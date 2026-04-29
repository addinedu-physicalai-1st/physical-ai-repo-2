"""보고서 endpoint 테스트."""
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_pending_lists_attended_children_without_reports(
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
        Attendance(child_id=c1.id, date=today, type="IN",
                   time=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc))
    )
    db_session.add(
        Attendance(child_id=c2.id, date=today, type="IN",
                   time=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc))
    )
    await db_session.flush()

    response = await teacher_client.get(
        f"/api/reports?status=pending&date={today.isoformat()}"
    )
    assert response.status_code == 200
    body = response.json()
    pending_child_ids = {r["child_id"] for r in body}
    assert pending_child_ids == {c1.id, c2.id}


async def test_pending_excludes_children_with_existing_report(
    teacher_client: AsyncClient, db_session
):
    from server.db.models import Attendance, Child, Report

    today = date.today()
    c1 = Child(name="A", birth_date=date(2021, 1, 1), class_name="햇살반",
               photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add(c1)
    await db_session.flush()
    db_session.add(
        Attendance(child_id=c1.id, date=today, type="IN",
                   time=datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc))
    )
    db_session.add(
        Report(child_id=c1.id, date=today, content="하원 후",
               created_at=datetime.now(timezone.utc))
    )
    await db_session.flush()

    response = await teacher_client.get(
        f"/api/reports?status=pending&date={today.isoformat()}"
    )
    body = response.json()
    assert all(r["child_id"] != c1.id for r in body)


async def test_pending_as_parent_returns_403(parent_client: AsyncClient):
    response = await parent_client.get(
        f"/api/reports?status=pending&date={date.today().isoformat()}"
    )
    assert response.status_code == 403


async def test_get_report_by_child_and_date(teacher_client: AsyncClient, db_session):
    from server.db.models import Child, Report

    today = date.today()
    c = Child(name="A", birth_date=date(2021, 1, 1), class_name="햇살반",
              photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add(c)
    await db_session.flush()
    r = Report(child_id=c.id, date=today, content="내용",
               created_at=datetime.now(timezone.utc))
    db_session.add(r)
    await db_session.flush()

    response = await teacher_client.get(
        f"/api/reports?child_id={c.id}&date={today.isoformat()}"
    )
    body = response.json()
    assert len(body) == 1
    assert body[0]["content"] == "내용"


async def test_patch_report_updates_content(teacher_client: AsyncClient, db_session):
    from server.db.models import Child, Report

    c = Child(name="A", birth_date=date(2021, 1, 1), class_name="햇살반",
              photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add(c)
    await db_session.flush()
    r = Report(child_id=c.id, date=date.today(), content="기존",
               created_at=datetime.now(timezone.utc))
    db_session.add(r)
    await db_session.flush()
    await db_session.commit()

    response = await teacher_client.patch(
        f"/api/reports/{r.id}",
        json={"content": "수정됨"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "수정됨"
    assert body["updated_at"] is not None


async def test_patch_nonexistent_report_returns_404(teacher_client: AsyncClient):
    response = await teacher_client.patch("/api/reports/99999", json={"content": "X"})
    assert response.status_code == 404


async def test_patch_report_as_parent_returns_403(parent_client: AsyncClient):
    response = await parent_client.patch("/api/reports/1", json={"content": "X"})
    assert response.status_code == 403
