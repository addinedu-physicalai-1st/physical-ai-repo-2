"""사진 endpoint 테스트."""
import uuid
from datetime import date, datetime, timezone
from io import BytesIO

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


def _jpeg_bytes() -> bytes:
    """최소 유효 JPEG (1×1 흰 픽셀). 디코딩 검증 자체는 endpoint 가 안 함 — content-type 만."""
    # 표준 1×1 흰색 JPEG.
    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707"
        "070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c"
        "1c2837292c30313434341f27393d38323c2e333432ffdb0043010909090c0b0c180d"
        "0d1832211c2132323232323232323232323232323232323232323232323232323232"
        "32323232323232323232323232323232323232323232323232ffc00011080001000103"
        "012200021101031101ffc4001f000001050101010101010000000000000000010203"
        "040506070809000affc400b51000020103030204030505040400000172011002030411"
        "05122131410613516107227114328191a1082342b1c11552d1f02433627282090a16"
        "1718191a25262728292a3435363738393a434445464748494a535455565758595a"
        "636465666768696a737475767778797a838485868788898a92939495969798999a"
        "a2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7"
        "d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffc4001f0100030101010"
        "1010101010101000000000000010203040506070809000affc400b511000201020404"
        "030407050404000102770001020311040521310612415107617113223281081442"
        "9115a1b1c12309335262f0156272d10a162434e125f11718191a262728292a3536"
        "3738393a434445464748494a535455565758595a636465666768696a7374757677"
        "78797a82838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4"
        "b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9ea"
        "f2f3f4f5f6f7f8f9faffda000c03010002110311003f00fbfcffd9"
    )


async def test_my_child_photos_returns_subject_matched(
    client: AsyncClient, make_user, db_session
):
    from control_db.models import Child, ParentChild, Photo, PhotoSubject

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
    from control_db.models import Child

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


async def test_my_child_photos_date_filter_uses_kst_boundary(
    client: AsyncClient, make_user, db_session
):
    """`?date=YYYY-MM-DD` 는 KST 자정 기준으로 필터링한다 (보고서 생성과 동일 경계).

    회귀 방지: 이전엔 `func.date(taken_at)` (세션 TZ=UTC) 로 평가돼 자정~09시 KST
    사진이 누락됐고, 그 결과 보고서엔 이벤트가 있으나 portal UI 의 photos 캐시는
    비어 thumbnail 이 안 떴다.
    """
    from control_db.models import Child, ParentChild, Photo, PhotoSubject

    parent = await make_user("p@x.com", "test1234", role="parent")
    child = Child(name="A", birth_date=date(2021, 1, 1), class_name="햇살반",
                  photo_url=None, created_at=datetime.now(timezone.utc))
    db_session.add(child)
    await db_session.flush()
    db_session.add(ParentChild(parent_id=parent.id, child_id=child.id))

    # 2026-05-14 01:49 KST = 2026-05-13 16:49 UTC
    # UTC date 로 자르면 '2026-05-13', KST date 로 자르면 '2026-05-14'.
    kst_2026_05_14_early = datetime(2026, 5, 13, 16, 49, 43, tzinfo=timezone.utc)
    photo = Photo(child_id=child.id, url="https://picsum.photos/seed/early-kst/400",
                  taken_at=kst_2026_05_14_early, emotion="happy", mode="ox-quiz")
    db_session.add(photo)
    await db_session.flush()
    db_session.add(PhotoSubject(photo_id=photo.id, child_id=child.id))
    await db_session.flush()

    await client.post(
        "/api/auth/cookie/login",
        data={"username": "p@x.com", "password": "test1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    # 보고서 날짜 (KST) 기준 — 사진이 반환돼야 한다.
    response = await client.get(f"/api/children/{child.id}/photos?date=2026-05-14")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1, "01:49 KST 사진이 KST 일자 보고서에 매칭돼야 함"

    # UTC 일자(2026-05-13) 로 조회하면 비어 있어야 한다 — 같은 사진이 두 일자에 잡히면 곤란.
    response_utc = await client.get(f"/api/children/{child.id}/photos?date=2026-05-13")
    assert response_utc.status_code == 200
    assert response_utc.json() == []


async def test_natural_upload_creates_photo(client: AsyncClient, db_session, tmp_path, monkeypatch):
    """자연 촬영 업로드 — JPEG 받아 디스크 + DB 저장."""
    from control_service import config as config_module
    from control_service.routers import photos as photos_module
    from control_db.models import Photo
    from sqlalchemy import select

    monkeypatch.setattr(config_module.settings, "photo_dir", str(tmp_path))
    monkeypatch.setattr(photos_module.settings, "photo_dir", str(tmp_path))
    # InsightFace 모델 로딩 (~10s) 회피 — 테스트는 face matching 자체를 검증하지 않으므로
    # "얼굴 미검출 (None)" 동작만 흉내낸다.
    monkeypatch.setattr(photos_module, "extract_embedding", lambda _: None)

    session_id = str(uuid.uuid4())
    files = {"file": ("shot.jpg", BytesIO(_jpeg_bytes()), "image/jpeg")}
    data = {
        "robot": "noriarm",
        "mode": "ox-quiz",
        "emotion": "happy",
        "score": "0.82",
        "session_id": session_id,
    }
    r = await client.post("/api/photos/natural", files=files, data=data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["already"] is False
    assert body["url"].startswith("/api/photos-static/natural/")
    assert body["url"].endswith(".jpg")

    rows = (await db_session.execute(select(Photo).where(Photo.id == body["photo_id"]))).scalars().all()
    assert len(rows) == 1
    photo = rows[0]
    assert photo.child_id is None
    assert photo.emotion == "happy"
    assert photo.mode == "ox-quiz"
    assert photo.robot == "noriarm"
    assert photo.trigger_session_id == session_id
    assert photo.emotion_score == pytest.approx(0.82)


async def test_natural_upload_is_idempotent_per_session(
    client: AsyncClient, db_session, tmp_path, monkeypatch
):
    """같은 session_id 로 두 번 호출하면 기존 행 그대로 반환 (already=True)."""
    from control_service import config as config_module
    from control_service.routers import photos as photos_module

    monkeypatch.setattr(config_module.settings, "photo_dir", str(tmp_path))
    monkeypatch.setattr(photos_module.settings, "photo_dir", str(tmp_path))
    monkeypatch.setattr(photos_module, "extract_embedding", lambda _: None)

    session_id = str(uuid.uuid4())
    payload_data = {
        "robot": "noriarm",
        "mode": "ox-quiz",
        "emotion": "happy",
        "score": "0.82",
        "session_id": session_id,
    }

    r1 = await client.post(
        "/api/photos/natural",
        files={"file": ("a.jpg", BytesIO(_jpeg_bytes()), "image/jpeg")},
        data=payload_data,
    )
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["already"] is False

    r2 = await client.post(
        "/api/photos/natural",
        files={"file": ("b.jpg", BytesIO(_jpeg_bytes()), "image/jpeg")},
        data=payload_data,
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["already"] is True
    assert body2["photo_id"] == body1["photo_id"]
    assert body2["url"] == body1["url"]


async def test_natural_upload_rejects_invalid_session_id(
    client: AsyncClient, tmp_path, monkeypatch
):
    from control_service import config as config_module
    from control_service.routers import photos as photos_module

    monkeypatch.setattr(config_module.settings, "photo_dir", str(tmp_path))
    monkeypatch.setattr(photos_module.settings, "photo_dir", str(tmp_path))

    r = await client.post(
        "/api/photos/natural",
        files={"file": ("a.jpg", BytesIO(_jpeg_bytes()), "image/jpeg")},
        data={
            "robot": "noriarm",
            "mode": "ox-quiz",
            "emotion": "happy",
            "score": "0.82",
            "session_id": "not-a-uuid",
        },
    )
    assert r.status_code == 400


async def test_natural_upload_rejects_non_jpeg(client: AsyncClient, tmp_path, monkeypatch):
    from control_service import config as config_module
    from control_service.routers import photos as photos_module

    monkeypatch.setattr(config_module.settings, "photo_dir", str(tmp_path))
    monkeypatch.setattr(photos_module.settings, "photo_dir", str(tmp_path))

    r = await client.post(
        "/api/photos/natural",
        files={"file": ("a.png", BytesIO(b"fake-png"), "image/png")},
        data={
            "robot": "noriarm",
            "mode": "ox-quiz",
            "emotion": "happy",
            "score": "0.82",
            "session_id": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 400
