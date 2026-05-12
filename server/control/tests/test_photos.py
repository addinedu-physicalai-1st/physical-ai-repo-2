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


async def test_natural_upload_creates_photo(client: AsyncClient, db_session, tmp_path, monkeypatch):
    """자연 촬영 업로드 — JPEG 받아 디스크 + DB 저장."""
    from server.control import config as config_module
    from server.control.routers import photos as photos_module
    from server.db.models import Photo
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
    from server.control import config as config_module
    from server.control.routers import photos as photos_module

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
    from server.control import config as config_module
    from server.control.routers import photos as photos_module

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
    from server.control import config as config_module
    from server.control.routers import photos as photos_module

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
