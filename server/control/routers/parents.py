"""학부모 user 생성/수정 — initial_password 자동 발급 후 평문 응답."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi_users.password import PasswordHelper
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.control.deps import require_teacher
from server.control.schemas import (
    ParentInfoOut,
    ParentPatchPayload,
    RegisterParentPayload,
    RegisterParentResponse,
)
from server.db.models import Child, ParentChild, User
from server.db.session import get_session

router = APIRouter(prefix="/api", tags=["parents"])

_password_helper = PasswordHelper()


@router.post(
    "/parents",
    response_model=RegisterParentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_parent(
    payload: RegisterParentPayload,
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_session),
) -> RegisterParentResponse:
    child = await session.get(Child, payload.child_id)
    if not child:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Child not found")

    initial_password = "1234"

    user = User(
        email=payload.email,
        hashed_password=_password_helper.hash(initial_password),
        is_active=True,
        is_verified=True,
        is_superuser=False,
        role="parent",
        name=payload.name,
        phone=payload.phone,
    )
    session.add(user)
    await session.flush()  # user.id 확보

    session.add(ParentChild(parent_id=user.id, child_id=child.id))
    await session.commit()

    return RegisterParentResponse(
        parent=ParentInfoOut(
            id=user.id,
            name=user.name,
            email=user.email,
            phone=user.phone or "",
            child_ids=[child.id],
        ),
        initial_password=initial_password,
    )


@router.patch("/parents/{parent_id}", response_model=ParentInfoOut)
async def update_parent(
    parent_id: UUID,
    payload: ParentPatchPayload,
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_session),
) -> ParentInfoOut:
    user = await session.get(User, parent_id)
    if not user or user.role != "parent":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Parent not found")

    if payload.email is not None and payload.email != user.email:
        dup = (
            await session.execute(select(User).where(User.email == payload.email))
        ).scalar_one_or_none()
        if dup and dup.id != user.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use")
        user.email = payload.email
    if payload.name is not None:
        user.name = payload.name
    if payload.phone is not None:
        user.phone = payload.phone

    await session.commit()

    rows = await session.execute(
        select(ParentChild.child_id).where(ParentChild.parent_id == user.id)
    )
    child_ids = [r[0] for r in rows.all()]

    return ParentInfoOut(
        id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone or "",
        child_ids=child_ids,
    )
