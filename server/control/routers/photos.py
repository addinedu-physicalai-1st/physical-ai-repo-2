"""사진 — 학부모 조회 + 자연 촬영 업로드."""
from __future__ import annotations

import re
import secrets
from datetime import date as DateType, datetime, timezone, timedelta
from pathlib import Path
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.control.auth import current_active_user
from server.control.config import settings
from server.control.face_recognition import extract_embedding
from server.control.schemas import NaturalPhotoOut, PhotoOut
from server.db.models import ChildFaceEmbedding, ParentChild, Photo, PhotoSubject, User
from server.db.session import get_session

router = APIRouter(prefix="/api", tags=["photos"])

# 자연 촬영 업로드 시 face matching cutoff — InsightFace L2-normalized 임베딩의 cosine 거리.
# 0.55 ≈ similarity 0.45. 같은 사람: 보통 0.3~0.5 (안전 마진 + 각도 변화 흡수), 타인: 0.7+.
_FACE_MATCH_MAX_DISTANCE = 0.55

# 파일명 안에 들어가는 슬러그 sanitize — 모드명에 한글이 들어와도 안전한 ASCII slug 로.
_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")

# 보고서 시간대 — 파일명의 HHMMSS 는 KST 기준 (보고서가 사람이 읽는 시각 그대로).
_KST = timezone(timedelta(hours=9))


def _slugify(value: str, fallback: str = "unknown") -> str:
    s = _SLUG_RE.sub("-", value.strip()).strip("-")
    return (s[:32] or fallback).lower()


def _photo_disk_path(photo_url: str) -> Optional[Path]:
    """photo.url (`/api/photos-static/natural/.../x.jpg`) → 실제 디스크 경로."""
    prefix = "/api/photos-static/"
    if not photo_url.startswith(prefix):
        return None
    return Path(settings.photo_dir) / photo_url[len(prefix):]


async def classify_unmapped_photos_for_date(
    session: AsyncSession,
    target_date: DateType,
) -> int:
    """해당 일자의 자연 촬영 사진 중 photo_subject 매핑이 없는 것을 face matching 으로 분류.

    교사가 "AI 보고서 생성" 트리거 시 이 함수를 먼저 호출해 미분류 사진을 back-fill 한다.
    이미 매핑된 사진은 건너뛴다 (idempotent). 매칭 실패한 사진은 그대로 둔다 — 다음 트리거에서
    다시 시도된다.

    반환: 새로 매핑된 사진 개수.
    """
    day_start_kst = datetime.combine(target_date, datetime.min.time(), _KST)
    day_end_kst = day_start_kst + timedelta(days=1)
    rows = (
        await session.execute(
            select(Photo)
            .outerjoin(PhotoSubject, PhotoSubject.photo_id == Photo.id)
            .where(
                Photo.taken_at >= day_start_kst,
                Photo.taken_at < day_end_kst,
                PhotoSubject.photo_id.is_(None),
            )
        )
    ).scalars().all()
    if not rows:
        return 0

    classified = 0
    for photo in rows:
        abs_path = _photo_disk_path(photo.url)
        if abs_path is None or not abs_path.is_file():
            continue
        emb = extract_embedding(abs_path.read_bytes())
        if emb is None:
            continue
        nearest = (
            await session.execute(
                select(
                    ChildFaceEmbedding.child_id,
                    ChildFaceEmbedding.embedding.cosine_distance(emb).label("dist"),
                )
                .order_by("dist")
                .limit(1)
            )
        ).first()
        if nearest is None or nearest.dist >= _FACE_MATCH_MAX_DISTANCE:
            continue
        matched_id = int(nearest.child_id)
        photo.child_id = matched_id
        session.add(PhotoSubject(photo_id=photo.id, child_id=matched_id))
        classified += 1

    if classified > 0:
        await session.flush()
    return classified


@router.get(
    "/children/{child_id}/photos",
    response_model=list[PhotoOut],
)
async def list_child_photos(
    child_id: int,
    date: Optional[DateType] = Query(None),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[PhotoOut]:
    """photo_subject 매핑으로 자녀가 등장한 사진을 조회. 교사 = 모든 자녀, 학부모 = 본인 자녀만."""
    if user.role == "parent":
        mapping = await session.execute(
            select(ParentChild).where(
                ParentChild.parent_id == user.id,
                ParentChild.child_id == child_id,
            )
        )
        if mapping.scalar_one_or_none() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    elif user.role != "teacher":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")

    query = (
        select(Photo)
        .join(PhotoSubject, PhotoSubject.photo_id == Photo.id)
        .where(PhotoSubject.child_id == child_id)
        .order_by(Photo.taken_at.asc())
    )
    if date:
        query = query.where(func.date(Photo.taken_at) == date)

    rows = (await session.execute(query)).scalars().all()
    return [PhotoOut.model_validate(p, from_attributes=True) for p in rows]


@router.post(
    "/photos/natural",
    response_model=NaturalPhotoOut,
)
async def upload_natural_photo(
    file: UploadFile = File(...),
    robot: str = Form(...),
    mode: str = Form(...),
    emotion: Literal["happy", "sad"] = Form(...),
    score: float = Form(...),
    session_id: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> NaturalPhotoOut:
    """자연 촬영 — 로봇 UI 가 브라우저에서 감정 임계 초과 시 1프레임 업로드.

    DB `photo` 행 INSERT + 로컬 디스크 저장. `session_id` 는 한 게임 세션에서
    중복 업로드 방지를 위한 멱등키 — 같은 session_id 로 두 번째 요청이 오면
    기존 행을 그대로 돌려준다. AI 사진 분류 (얼굴 인식·photo_subject 매핑)
    는 후속 SR-PHOTO-002 에서 처리.
    """
    # session_id 검증 — UUID v4 포맷 강제 (멱등키 위변조 방지).
    try:
        UUID(session_id, version=4)
    except (ValueError, AttributeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "session_id must be UUID v4")

    # 이미 같은 session 으로 업로드된 행이 있으면 그대로 반환 (멱등).
    existing = await session.execute(
        select(Photo).where(Photo.trigger_session_id == session_id)
    )
    existing_row = existing.scalar_one_or_none()
    if existing_row is not None:
        return NaturalPhotoOut(
            photo_id=existing_row.id,
            url=existing_row.url,
            already=True,
        )

    if file.content_type not in {"image/jpeg", "image/jpg"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "JPEG only")

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")
    # 자연 촬영은 640×360 q=0.82 ≒ 30~80KB 수준. 512KB 면 후하게 잡은 상한.
    if len(data) > 512 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "image too large")

    now = datetime.now(timezone.utc)
    now_kst = now.astimezone(_KST)
    robot_slug = _slugify(robot, fallback="robot")
    mode_slug = _slugify(mode, fallback="mode")
    score_int = max(0, min(100, int(round(score * 100))))
    rand8 = secrets.token_hex(4)  # 8 hex chars
    filename = (
        f"{now_kst.strftime('%H%M%S')}_{robot_slug}_{mode_slug}_"
        f"{emotion}_s{score_int:02d}_{rand8}.jpg"
    )
    rel_dir = Path("natural") / now_kst.strftime("%Y") / now_kst.strftime("%m") / now_kst.strftime("%d")
    abs_dir = Path(settings.photo_dir) / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    (abs_dir / filename).write_bytes(data)

    # url 은 main.py StaticFiles 마운트 prefix 와 맞춤.
    url = f"/api/photos-static/{rel_dir.as_posix()}/{filename}"

    # 얼굴 매칭 — 등록 임베딩 (child_face_embedding) 과 cosine 거리로 가장 가까운 자녀를 트리거 child 로 확정.
    # pgvector `<=>` (cosine_distance) ORDER BY ASC 로 nearest neighbor 한 행만 가져온다.
    # 임베딩 추출은 동기 CPU 작업 (~수백 ms) — 업로드 latency 가 늘지만 OX 퀴즈 한 세션당 1장이라
    # ai_job 큐 분리 (SR-AI-001) 전엔 인라인으로 처리.
    matched_child_id: Optional[int] = None
    emb = extract_embedding(data)
    if emb is not None:
        nearest = (
            await session.execute(
                select(
                    ChildFaceEmbedding.child_id,
                    ChildFaceEmbedding.embedding.cosine_distance(emb).label("dist"),
                )
                .order_by("dist")
                .limit(1)
            )
        ).first()
        if nearest is not None and nearest.dist < _FACE_MATCH_MAX_DISTANCE:
            matched_child_id = int(nearest.child_id)

    photo = Photo(
        child_id=matched_child_id,
        url=url,
        taken_at=now,
        emotion=emotion,
        emotion_score=score,
        mode=mode,
        robot=robot,
        trigger_session_id=session_id,
    )
    session.add(photo)
    await session.flush()
    if matched_child_id is not None:
        session.add(PhotoSubject(photo_id=photo.id, child_id=matched_child_id))
    await session.commit()
    await session.refresh(photo)
    return NaturalPhotoOut(photo_id=photo.id, url=url, already=False)
