"""자녀 CRUD endpoint."""
import os
import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.control.config import settings
from server.control.deps import require_parent, require_teacher
from server.control.schemas import (
    ChildDetailOut,
    ChildOut,
    ChildPatchPayload,
    ParentInfoOut,
    RegisterChildPayload,
)
from server.control.face_recognition import extract_embedding
from server.db.models import (
    Child,
    ChildFaceEmbedding,
    ChildFaceImage,
    ChildTeacher,
    ParentChild,
    User,
)
from server.db.session import get_session

router = APIRouter(prefix="/api", tags=["children"])


@router.post("/children", response_model=ChildOut, status_code=status.HTTP_201_CREATED)
async def create_child(
    payload: RegisterChildPayload,
    teacher: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_session),
) -> ChildOut:
    child = Child(
        name=payload.name,
        birth_date=payload.birth_date,
        class_name=payload.class_name,
        photo_url=None,
        notes=payload.notes,
        created_at=datetime.now(timezone.utc),
    )
    session.add(child)
    await session.flush()  # id 확보

    session.add(ChildTeacher(teacher_id=teacher.id, child_id=child.id))
    await session.commit()

    return ChildOut.model_validate(child, from_attributes=True)


@router.get("/children", response_model=list[ChildOut])
async def list_children(
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_session),
) -> list[ChildOut]:
    result = await session.execute(select(Child).order_by(Child.class_name, Child.name))
    return [ChildOut.model_validate(c, from_attributes=True) for c in result.scalars()]


@router.get("/children/{child_id}", response_model=ChildDetailOut)
async def get_child(
    child_id: int,
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_session),
) -> ChildDetailOut:
    child = await session.get(Child, child_id)
    if not child:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    parent_rows = await session.execute(
        select(User, ParentChild.child_id)
        .join(ParentChild, ParentChild.parent_id == User.id)
        .where(ParentChild.child_id == child_id)
    )
    parents: list[ParentInfoOut] = []
    for user, _cid in parent_rows.all():
        parents.append(
            ParentInfoOut(
                id=user.id,
                name=user.name,
                email=user.email,
                phone=user.phone or "",
                child_ids=[child_id],
            )
        )

    return ChildDetailOut(
        id=child.id,
        name=child.name,
        birth_date=child.birth_date,
        class_name=child.class_name,
        photo_url=child.photo_url,
        notes=child.notes,
        parents=parents,
    )


@router.patch("/children/{child_id}", response_model=ChildOut)
async def patch_child(
    child_id: int,
    payload: ChildPatchPayload,
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_session),
) -> ChildOut:
    child = await session.get(Child, child_id)
    if not child:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Child not found")
    if payload.notes is not None:
        child.notes = payload.notes
    await session.commit()
    return ChildOut.model_validate(child, from_attributes=True)


@router.get("/parent/children", response_model=list[ChildOut])
async def my_children(
    parent: User = Depends(require_parent),
    session: AsyncSession = Depends(get_session),
) -> list[ChildOut]:
    result = await session.execute(
        select(Child)
        .join(ParentChild, ParentChild.child_id == Child.id)
        .where(ParentChild.parent_id == parent.id)
        .order_by(Child.name)
    )
    return [ChildOut.model_validate(c, from_attributes=True) for c in result.scalars()]


@router.post(
    "/children/{child_id}/face-images",
    status_code=status.HTTP_200_OK,
)
async def upload_face_images(
    child_id: int,
    files: list[UploadFile] = File(...),
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_session),
) -> dict:
    child = await session.get(Child, child_id)
    if not child:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Child not found")

    save_dir = os.path.join(settings.face_image_dir, str(child_id))

    # 재촬영: 기존 파일·DB row·임베딩 모두 정리
    await session.execute(
        delete(ChildFaceEmbedding).where(ChildFaceEmbedding.child_id == child_id)
    )
    await session.execute(
        delete(ChildFaceImage).where(ChildFaceImage.child_id == child_id)
    )
    if os.path.isdir(save_dir):
        shutil.rmtree(save_dir)
    os.makedirs(save_dir, exist_ok=True)

    angles = ["front", "left", "right", "up", "down"]
    saved = 0
    embeddings_added = 0
    for i, upload in enumerate(files):
        path = os.path.join(save_dir, f"{i}.jpg")
        content = await upload.read()
        with open(path, "wb") as f:
            f.write(content)

        face_image = ChildFaceImage(
            child_id=child_id,
            file_path=path,
            angle=angles[i] if i < len(angles) else None,
            uploaded_at=datetime.now(timezone.utc),
        )
        session.add(face_image)
        await session.flush()
        saved += 1

        emb = extract_embedding(content)
        if emb is not None:
            session.add(
                ChildFaceEmbedding(
                    child_id=child_id,
                    face_image_id=face_image.id,
                    embedding=emb,
                )
            )
            embeddings_added += 1

    # 정적 mount 가 settings.face_image_dir 를 /api/face-images 로 노출한다 (server/control/main.py)
    child.photo_url = f"/api/face-images/{child_id}/0.jpg" if files else None

    await session.commit()
    return {"uploaded": saved, "embeddings": embeddings_added}
