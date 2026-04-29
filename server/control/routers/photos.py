"""사진 조회 — 학부모 본인 자녀 한정."""
from datetime import date as DateType
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.control.deps import assert_my_child
from server.control.schemas import PhotoOut
from server.db.models import Photo, PhotoSubject
from server.db.session import get_session

router = APIRouter(prefix="/api", tags=["photos"])


@router.get(
    "/children/{child_id}/photos",
    response_model=list[PhotoOut],
)
async def list_child_photos(
    child_id: int = Depends(assert_my_child),
    date: Optional[DateType] = Query(None),
    session: AsyncSession = Depends(get_session),
) -> list[PhotoOut]:
    """photo_subject 매핑으로 자녀가 등장한 사진을 조회."""
    query = (
        select(Photo)
        .join(PhotoSubject, PhotoSubject.photo_id == Photo.id)
        .where(PhotoSubject.child_id == child_id)
        .order_by(Photo.taken_at.desc())
    )
    if date:
        query = query.where(func.date(Photo.taken_at) == date)

    rows = (await session.execute(query)).scalars().all()
    return [PhotoOut.model_validate(p, from_attributes=True) for p in rows]
