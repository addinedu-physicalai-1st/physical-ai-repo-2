"""/api/teachers/* — 교사 프로필 + 얼굴 등록·매칭 (SR-REG-011/012, SR-OPS-019, SR-CAR-009)."""
import os
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from control_service.config import settings
from control_service.deps import require_device_token, require_teacher
from control_service.face_recognition import extract_embedding
from control_service.schemas import (
    TeacherColleagueOut,
    TeacherFaceStatusOut,
    TeacherMatchOut,
    TeacherProfileOut,
    TeacherUpdatePayload,
)
from control_db.models import TeacherFaceEmbedding, TeacherFaceImage, User
from control_db.session import get_session

router = APIRouter(prefix="/api/teachers", tags=["teachers"])


# 교사 얼굴 파일은 자녀 얼굴(`settings.face_image_dir`) 와 평행한 별도 디렉토리에 저장.
TEACHER_FACE_DIR = "db/storage/teacher-faces"


async def _profile_out(db: AsyncSession, user: User) -> TeacherProfileOut:
    img_count = len(
        (
            await db.execute(
                select(TeacherFaceImage.id).where(
                    TeacherFaceImage.teacher_id == user.id
                )
            )
        )
        .scalars()
        .all()
    )
    has_embedding = (
        (
            await db.execute(
                select(TeacherFaceEmbedding.id)
                .where(TeacherFaceEmbedding.teacher_id == user.id)
                .limit(1)
            )
        ).first()
        is not None
    )
    return TeacherProfileOut(
        id=user.id,
        email=user.email,
        name=user.name,
        phone=user.phone,
        birth_date=user.birth_date,
        address=user.address,
        class_name=user.class_name,
        hired_date=user.hired_date,
        emergency_contact=user.emergency_contact,
        photo_url=user.photo_url,
        face_registered=has_embedding,
        face_image_count=img_count,
    )


@router.get("/", response_model=list[TeacherColleagueOut])
async def list_teachers(
    _: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_session),
) -> list[TeacherColleagueOut]:
    rows = (
        (
            await db.execute(
                select(User).where(User.role == "teacher").order_by(User.name)
            )
        )
        .scalars()
        .all()
    )
    return [
        TeacherColleagueOut(
            id=u.id,
            name=u.name,
            class_name=u.class_name,
            phone=u.phone,
            emergency_contact=u.emergency_contact,
            photo_url=u.photo_url,
            hired_date=u.hired_date,
        )
        for u in rows
    ]


@router.get("/me", response_model=TeacherProfileOut)
async def get_me(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_session),
) -> TeacherProfileOut:
    return await _profile_out(db, current_user)


@router.patch("/me", response_model=TeacherProfileOut)
async def patch_me(
    payload: TeacherUpdatePayload,
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_session),
) -> TeacherProfileOut:
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(current_user, key, value)
    await db.commit()
    await db.refresh(current_user)
    return await _profile_out(db, current_user)


_FACE_ANGLES = ["front", "left", "right", "up", "down"]


@router.post("/me/face-images", response_model=TeacherFaceStatusOut)
async def upload_face_images(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_session),
) -> TeacherFaceStatusOut:
    if not files:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "files 가 비어 있습니다")

    # 재캡처: 기존 row + 디스크 파일 모두 정리
    await db.execute(
        delete(TeacherFaceEmbedding).where(
            TeacherFaceEmbedding.teacher_id == current_user.id
        )
    )
    await db.execute(
        delete(TeacherFaceImage).where(TeacherFaceImage.teacher_id == current_user.id)
    )

    save_dir = os.path.join(TEACHER_FACE_DIR, str(current_user.id))
    if os.path.isdir(save_dir):
        shutil.rmtree(save_dir)
    os.makedirs(save_dir, exist_ok=True)

    saved = 0
    embeddings_added = 0
    for idx, upload in enumerate(files):
        path = os.path.join(save_dir, f"{idx}.jpg")
        content = await upload.read()
        with open(path, "wb") as f:
            f.write(content)

        img = TeacherFaceImage(
            teacher_id=current_user.id,
            file_path=path,
            angle=_FACE_ANGLES[idx] if idx < len(_FACE_ANGLES) else None,
            uploaded_at=datetime.now(timezone.utc),
        )
        db.add(img)
        await db.flush()
        saved += 1

        emb = extract_embedding(content)
        if emb is not None:
            db.add(
                TeacherFaceEmbedding(
                    teacher_id=current_user.id,
                    face_image_id=img.id,
                    embedding=emb,
                )
            )
            embeddings_added += 1

    # 첫 사진(idx=0, "front" 각도) 을 프로필 사진으로 자동 갱신.
    # static mount: /api/teacher-faces/{teacher_id}/0.jpg → TEACHER_FACE_DIR/{teacher_id}/0.jpg
    if saved > 0:
        current_user.photo_url = f"/api/teacher-faces/{current_user.id}/0.jpg"
    else:
        current_user.photo_url = None

    await db.commit()
    return TeacherFaceStatusOut(
        registered=embeddings_added > 0,
        image_count=saved,
        updated_at=datetime.now(timezone.utc),
    )


@router.post("/match-face", response_model=TeacherMatchOut)
async def match_face(
    file: UploadFile = File(...),
    _: None = Depends(require_device_token),
    db: AsyncSession = Depends(get_session),
) -> TeacherMatchOut:
    """입력 얼굴 이미지를 등록 교사 임베딩과 비교해 가장 가까운 교사를 반환한다.

    pgvector cosine distance (`<=>`) 최소값을 채택. `settings.face_match_threshold`
    (0.45) 이하만 matched=true. 등록된 교사 임베딩이 없으면 matched=false.

    인증: robot-web (GogoPing) 의 추종 진입 게이트에서 호출하므로 device token 만 허용.
    teacher 세션 사용처가 생기면 OR 의존으로 확장."""
    threshold = settings.face_match_threshold

    content = await file.read()
    probe = extract_embedding(content)
    if probe is None:
        return TeacherMatchOut(
            teacher_id=None,
            name=None,
            distance=None,
            threshold=threshold,
            matched=False,
        )

    row = (
        await db.execute(
            select(
                User.id.label("teacher_id"),
                User.name.label("teacher_name"),
                TeacherFaceEmbedding.embedding.cosine_distance(probe).label("dist"),
            )
            .join(TeacherFaceEmbedding, TeacherFaceEmbedding.teacher_id == User.id)
            .order_by("dist")
            .limit(1)
        )
    ).first()

    if row is None:
        return TeacherMatchOut(
            teacher_id=None,
            name=None,
            distance=None,
            threshold=threshold,
            matched=False,
        )

    distance = float(row.dist)
    matched = distance <= threshold
    return TeacherMatchOut(
        teacher_id=row.teacher_id if matched else None,
        name=row.teacher_name if matched else None,
        distance=distance,
        threshold=threshold,
        matched=matched,
    )


@router.get("/me/face-status", response_model=TeacherFaceStatusOut)
async def face_status(
    current_user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_session),
) -> TeacherFaceStatusOut:
    imgs = (
        (
            await db.execute(
                select(TeacherFaceImage)
                .where(TeacherFaceImage.teacher_id == current_user.id)
                .order_by(TeacherFaceImage.uploaded_at.desc())
            )
        )
        .scalars()
        .all()
    )
    latest = imgs[0].uploaded_at if imgs else None
    has_embedding = (
        (
            await db.execute(
                select(TeacherFaceEmbedding.id)
                .where(TeacherFaceEmbedding.teacher_id == current_user.id)
                .limit(1)
            )
        ).first()
        is not None
    )
    return TeacherFaceStatusOut(
        registered=has_embedding,
        image_count=len(imgs),
        updated_at=latest,
    )
