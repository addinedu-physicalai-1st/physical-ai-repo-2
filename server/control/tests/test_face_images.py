"""얼굴 이미지 업로드 테스트."""
import io
import os

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _create_child(client: AsyncClient) -> int:
    response = await client.post(
        "/api/children",
        json={"name": "민준", "birth_date": "2021-03-12", "class_name": "햇살반"},
    )
    return response.json()["id"]


def _fake_jpeg(size: int = 100) -> bytes:
    """SOI/EOI 만 있는 더미 JPEG bytes."""
    return b"\xff\xd8" + b"\x00" * size + b"\xff\xd9"


async def test_upload_5_face_images_returns_200_and_uploaded_count(
    teacher_client: AsyncClient, tmp_path, monkeypatch
):
    # face_image_dir 을 tmp_path 로 override
    from server.control.config import settings
    monkeypatch.setattr(settings, "face_image_dir", str(tmp_path))

    cid = await _create_child(teacher_client)

    files = [
        ("files", (f"face_{i}.jpg", io.BytesIO(_fake_jpeg()), "image/jpeg"))
        for i in range(5)
    ]
    response = await teacher_client.post(
        f"/api/children/{cid}/face-images",
        files=files,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["uploaded"] == 5
    # 더미 JPEG 라 임베딩은 0건
    assert body["embeddings"] == 0

    # 파일 5장 디스크에 있음
    saved_dir = tmp_path / str(cid)
    assert saved_dir.exists()
    assert len(list(saved_dir.glob("*.jpg"))) == 5


async def test_upload_to_nonexistent_child_returns_404(
    teacher_client: AsyncClient, tmp_path, monkeypatch
):
    from server.control.config import settings
    monkeypatch.setattr(settings, "face_image_dir", str(tmp_path))

    files = [("files", ("face_0.jpg", io.BytesIO(_fake_jpeg()), "image/jpeg"))]
    response = await teacher_client.post(
        "/api/children/99999/face-images",
        files=files,
    )
    assert response.status_code == 404


async def test_upload_as_parent_returns_403(
    parent_client: AsyncClient, tmp_path, monkeypatch
):
    from server.control.config import settings
    monkeypatch.setattr(settings, "face_image_dir", str(tmp_path))

    files = [("files", ("face_0.jpg", io.BytesIO(_fake_jpeg()), "image/jpeg"))]
    response = await parent_client.post(
        "/api/children/1/face-images",
        files=files,
    )
    assert response.status_code == 403
