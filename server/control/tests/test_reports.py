"""보고서 endpoint 테스트."""
import json
from datetime import date, datetime, timezone, timedelta

import httpx
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


_KST = timezone(timedelta(hours=9))


def _install_ai_hub_mock(monkeypatch, *, response_json: dict):
    """Control Server reports 라우터의 httpx.AsyncClient 를 MockTransport 로 교체.

    반환된 dict 의 `last_request` 에 마지막 호출 payload 가 저장됨 — assertion 용.
    """
    state: dict = {"last_request": None}

    def handler(request: httpx.Request) -> httpx.Response:
        state["last_request"] = request
        return httpx.Response(200, json=response_json)

    orig_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs.pop("timeout", None)
        return orig_async_client(transport=httpx.MockTransport(handler))

    from server.control.routers import reports as reports_module

    monkeypatch.setattr(reports_module.httpx, "AsyncClient", fake_async_client)
    return state


async def test_pending_lists_children_without_reports(
    teacher_client: AsyncClient, db_session
):
    """등원 여부와 무관하게, 해당 일 보고서가 없으면 pending 에 포함된다."""
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
    await db_session.flush()

    response = await teacher_client.get(
        f"/api/reports?status=pending&date={today.isoformat()}"
    )
    assert response.status_code == 200
    body = response.json()
    pending_child_ids = {r["child_id"] for r in body}
    assert pending_child_ids == {c1.id, c2.id}
    by_id = {r["child_id"]: r for r in body}
    assert by_id[c1.id]["attendance_debug"]["has_check_in"] is True
    assert by_id[c1.id]["attendance_debug"]["has_check_out"] is False
    assert by_id[c2.id]["attendance_debug"]["has_check_in"] is False
    assert by_id[c2.id]["attendance_debug"]["has_check_out"] is False


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
    ad = body[0]["attendance_debug"]
    assert ad["has_check_in"] is False
    assert ad["has_check_out"] is False
    assert ad["check_in_kst"] is None
    assert ad["check_out_kst"] is None


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
    assert body["attendance_debug"]["has_check_in"] is False


async def test_patch_nonexistent_report_returns_404(teacher_client: AsyncClient):
    response = await teacher_client.patch("/api/reports/99999", json={"content": "X"})
    assert response.status_code == 404


async def test_patch_report_as_parent_returns_403(parent_client: AsyncClient):
    response = await parent_client.patch("/api/reports/1", json={"content": "X"})
    assert response.status_code == 403


async def test_delete_report_removes_row(teacher_client: AsyncClient, db_session):
    from server.db.models import Child, Report
    from sqlalchemy import select

    c = Child(
        name="DelKid",
        birth_date=date(2021, 1, 1),
        class_name="햇살반",
        photo_url=None,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(c)
    await db_session.flush()
    r = Report(
        child_id=c.id,
        date=date.today(),
        content="{}",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(r)
    await db_session.flush()
    await db_session.commit()
    rid = r.id

    response = await teacher_client.delete(f"/api/reports/{rid}")
    assert response.status_code == 204

    rows = (await db_session.execute(select(Report).where(Report.id == rid))).scalars().all()
    assert len(rows) == 0


async def test_delete_report_not_found_returns_404(teacher_client: AsyncClient):
    response = await teacher_client.delete("/api/reports/99999")
    assert response.status_code == 404


async def test_delete_report_as_parent_returns_403(parent_client: AsyncClient):
    response = await parent_client.delete("/api/reports/1")
    assert response.status_code == 403


async def test_generate_report_inserts_new_row(
    teacher_client: AsyncClient, db_session, monkeypatch
):
    """AI Hub mock → /api/reports/generate 로 새 행 INSERT."""
    from server.db.models import Child, Menu, Photo, PhotoSubject, Report
    from sqlalchemy import select

    c = Child(
        name="박우림",
        birth_date=date(2021, 1, 1),
        class_name="햇살반",
        photo_url=None,
        created_at=datetime.now(timezone.utc),
        notes="활동 시 선생님 말에 잘 귀 기울이는 편.",
    )
    db_session.add(c)
    await db_session.flush()
    today = date(2026, 5, 12)
    # 10:23 KST = 01:23 UTC
    p = Photo(
        child_id=c.id,
        url="/api/photos-static/x.jpg",
        taken_at=datetime(2026, 5, 12, 1, 23, tzinfo=timezone.utc),
        emotion="happy", emotion_score=0.82, mode="ox-quiz", robot="noriarm",
        trigger_session_id="00000000-0000-4000-8000-000000000001",
    )
    db_session.add(p)
    await db_session.flush()
    # photo_subject 매핑 — 이 자녀가 등장한 사진으로만 보고서 생성에 포함되도록.
    db_session.add(PhotoSubject(photo_id=p.id, child_id=c.id))
    db_session.add(Menu(day=12, items=["김밥", "단무지"]))
    await db_session.flush()
    await db_session.commit()

    mock_state = _install_ai_hub_mock(
        monkeypatch,
        response_json={"content": "지수 어린이는 오늘 OX 퀴즈를 즐겁게 풀었습니다."},
    )

    response = await teacher_client.post(
        "/api/reports/generate",
        json={"child_id": c.id, "date": today.isoformat()},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "OX 퀴즈" in body["content"]
    assert body["child_id"] == c.id
    assert body["attendance_debug"]["has_check_in"] is False
    assert body["attendance_debug"]["has_check_out"] is False

    rows = (await db_session.execute(select(Report).where(Report.child_id == c.id))).scalars().all()
    assert len(rows) == 1

    # AI Hub 에 보낸 payload 검증 — child_name + KST 시각 + 메뉴 + 특이사항
    sent = mock_state["last_request"].content.decode()
    assert "10:23" in sent
    assert "김밥" in sent
    sent_payload = json.loads(sent)
    assert sent_payload.get("child_name") == "우림"
    assert sent_payload.get("registered_full_name") == "박우림"
    assert sent_payload.get("class_name") == "햇살반"
    assert sent_payload.get("birth_date") == "2021-01-01"
    assert sent_payload.get("child_notes") == "활동 시 선생님 말에 잘 귀 기울이는 편."
    assert "attendance" in sent_payload
    assert sent_payload["attendance"]["check_in_kst"] is None


async def test_generate_report_attendance_debug_matches_db(
    teacher_client: AsyncClient, db_session, monkeypatch
):
    from server.db.models import Attendance, Child, Menu

    c = Child(
        name="김출석",
        birth_date=date(2021, 1, 1),
        class_name="햇살반",
        photo_url=None,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(c)
    await db_session.flush()
    day = date(2026, 5, 12)
    # 09:00 / 15:00 KST
    t_in = datetime(2026, 5, 12, 0, 0, tzinfo=timezone.utc)
    t_out = datetime(2026, 5, 12, 6, 0, tzinfo=timezone.utc)
    db_session.add(Attendance(child_id=c.id, date=day, type="IN", time=t_in))
    db_session.add(Attendance(child_id=c.id, date=day, type="OUT", time=t_out))
    db_session.add(Menu(day=12, items=["밥"]))
    await db_session.flush()
    await db_session.commit()

    _install_ai_hub_mock(monkeypatch, response_json={"content": "{}"})

    response = await teacher_client.post(
        "/api/reports/generate",
        json={"child_id": c.id, "date": day.isoformat()},
    )
    assert response.status_code == 200, response.text
    ad = response.json()["attendance_debug"]
    assert ad["has_check_in"] is True
    assert ad["has_check_out"] is True
    assert ad["check_in_kst"] == "09:00"
    assert ad["check_out_kst"] == "15:00"


async def test_generate_report_upserts_existing(
    teacher_client: AsyncClient, db_session, monkeypatch
):
    """이미 있는 보고서를 다시 생성하면 content 덮어쓰기 + updated_at 갱신."""
    from server.db.models import Child, Report
    from sqlalchemy import select

    c = Child(name="A", birth_date=date(2021, 1, 1), class_name="햇살반",
              photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add(c)
    await db_session.flush()
    today = date(2026, 5, 12)
    db_session.add(Report(child_id=c.id, date=today, content="이전 보고서",
                          created_at=datetime.now(timezone.utc)))
    await db_session.flush()
    await db_session.commit()

    _install_ai_hub_mock(monkeypatch, response_json={"content": "새로 작성된 내용"})

    response = await teacher_client.post(
        "/api/reports/generate",
        json={"child_id": c.id, "date": today.isoformat()},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "새로 작성된 내용"
    assert body["updated_at"] is not None

    rows = (await db_session.execute(select(Report).where(Report.child_id == c.id))).scalars().all()
    assert len(rows) == 1


async def test_generate_report_excludes_other_childs_photos(
    teacher_client: AsyncClient, db_session, monkeypatch
):
    """photo_subject 매핑이 없는 자녀로 보고서 생성하면 photo_events 가 비어 있어야 한다.

    같은 날 다른 아이 사진이 DB 에 있어도, photo_subject 매핑이 없는 대상 자녀의
    LLM payload 에는 그 사진의 감정·시각이 절대 들어가면 안 된다 (user-reported bug).
    """
    from server.db.models import Child, Photo, PhotoSubject
    import json

    me = Child(name="우리아이", birth_date=date(2021, 1, 1), class_name="햇살반",
               photo_url=None, created_at=datetime.now(timezone.utc))
    other = Child(name="다른아이", birth_date=date(2021, 2, 2), class_name="햇살반",
                  photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add_all([me, other])
    await db_session.flush()
    today = date(2026, 5, 12)
    other_photo = Photo(
        child_id=other.id,
        url="/api/photos-static/other.jpg",
        taken_at=datetime(2026, 5, 12, 1, 23, tzinfo=timezone.utc),
        emotion="happy", emotion_score=0.91, mode="ox-quiz", robot="noriarm",
        trigger_session_id="00000000-0000-4000-8000-00000000beef",
    )
    db_session.add(other_photo)
    await db_session.flush()
    db_session.add(PhotoSubject(photo_id=other_photo.id, child_id=other.id))
    await db_session.flush()
    await db_session.commit()

    mock_state = _install_ai_hub_mock(
        monkeypatch,
        response_json={"content": "오늘은 표정 기록이 없습니다."},
    )

    response = await teacher_client.post(
        "/api/reports/generate",
        json={"child_id": me.id, "date": today.isoformat()},
    )
    assert response.status_code == 200, response.text

    sent_payload = json.loads(mock_state["last_request"].content.decode())
    assert sent_payload["photo_events"] == [], (
        f"다른 아이 사진이 새는 중: {sent_payload['photo_events']}"
    )


async def test_generate_report_backfills_unmapped_photo_classification(
    teacher_client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """업로드 시점에 매핑이 누락된 사진을 보고서 생성 시 face matching 으로 back-fill 한다.

    photo_subject 행이 없는 자연 촬영 사진이 disk 에 있을 때, /api/reports/generate
    를 호출하면 face matching 으로 child_id 가 결정되고 photo_subject 가 INSERT 된다.
    """
    from server.control import config as config_module
    from server.control.routers import photos as photos_module
    from server.db.models import Child, ChildFaceEmbedding, Photo, PhotoSubject
    from sqlalchemy import select
    from pathlib import Path
    import json

    # tmp_path 를 photo_dir 로 — 디스크 읽기가 거기서 일어나도록.
    monkeypatch.setattr(config_module.settings, "photo_dir", str(tmp_path))
    monkeypatch.setattr(photos_module.settings, "photo_dir", str(tmp_path))

    # 등록된 자녀 1명 + 512-d 임베딩 1개. 동일 벡터로 mock 하면 cosine_distance = 0.
    me = Child(name="우리아이", birth_date=date(2021, 1, 1), class_name="햇살반",
               photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add(me)
    await db_session.flush()
    ref_emb = [0.0] * 511 + [1.0]
    db_session.add(ChildFaceEmbedding(child_id=me.id, embedding=ref_emb))
    await db_session.flush()

    # 매핑이 빠진 자연 촬영 사진 — 디스크 + DB.
    rel = "natural/2026/05/12/100000_noriarm_ox-quiz_happy_s82_aaaaaaaa.jpg"
    disk_path = Path(str(tmp_path)) / rel
    disk_path.parent.mkdir(parents=True, exist_ok=True)
    disk_path.write_bytes(b"\xff\xd8\xff")  # dummy — extract_embedding 는 mock 됨
    today = date(2026, 5, 12)
    p = Photo(
        child_id=None,
        url=f"/api/photos-static/{rel}",
        taken_at=datetime(2026, 5, 12, 1, 0, tzinfo=timezone.utc),
        emotion="happy", emotion_score=0.82, mode="ox-quiz", robot="noriarm",
        trigger_session_id="00000000-0000-4000-8000-cafebabe0001",
    )
    db_session.add(p)
    await db_session.flush()
    await db_session.commit()

    # extract_embedding 을 ref_emb 로 — distance=0, threshold(0.55) 통과 보장.
    monkeypatch.setattr(photos_module, "extract_embedding", lambda _: ref_emb)

    mock_state = _install_ai_hub_mock(
        monkeypatch, response_json={"content": "오늘 활짝 웃었어요."}
    )

    response = await teacher_client.post(
        "/api/reports/generate",
        json={"child_id": me.id, "date": today.isoformat()},
    )
    assert response.status_code == 200, response.text

    # back-fill 확인 — photo_subject 행이 새로 생기고 photo.child_id 도 채워짐.
    await db_session.refresh(p)
    assert p.child_id == me.id
    subject_rows = (
        await db_session.execute(
            select(PhotoSubject).where(PhotoSubject.photo_id == p.id)
        )
    ).scalars().all()
    assert len(subject_rows) == 1
    assert subject_rows[0].child_id == me.id

    # LLM payload 에도 이 사진의 시각이 포함되어야 한다.
    sent = json.loads(mock_state["last_request"].content.decode())
    assert len(sent["photo_events"]) == 1
    assert sent["photo_events"][0]["emotion"] == "happy"


async def test_generate_report_rejects_future_date(teacher_client: AsyncClient, db_session):
    from server.db.models import Child

    c = Child(
        name="X",
        birth_date=date(2021, 1, 1),
        class_name="햇살반",
        photo_url=None,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(c)
    await db_session.flush()
    await db_session.commit()

    response = await teacher_client.post(
        "/api/reports/generate",
        json={"child_id": c.id, "date": "2099-01-01"},
    )
    assert response.status_code == 400


async def test_generate_report_rejects_parent(parent_client: AsyncClient):
    response = await parent_client.post(
        "/api/reports/generate",
        json={"child_id": 1, "date": "2026-05-12"},
    )
    assert response.status_code == 403


async def test_generate_report_404_for_unknown_child(teacher_client: AsyncClient):
    response = await teacher_client.post(
        "/api/reports/generate",
        json={"child_id": 99999, "date": "2026-05-12"},
    )
    assert response.status_code == 404
