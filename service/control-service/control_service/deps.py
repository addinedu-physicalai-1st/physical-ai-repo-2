"""권한 dependency — require_role / assert_my_child / require_device_token."""
from typing import Literal, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control_service.auth import current_active_user
from control_service.config import settings
from control_db.models import ParentChild, User
from control_db.session import get_session


def require_role(role: Literal["teacher", "parent"]):
    """역할 일치 확인 — 다르면 403."""
    async def dep(user: User = Depends(current_active_user)) -> User:
        if user.role != role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
        return user
    return dep


require_teacher = require_role("teacher")
require_parent = require_role("parent")


async def assert_my_child(
    child_id: int,
    user: User = Depends(require_parent),
    session: AsyncSession = Depends(get_session),
) -> int:
    """학부모가 자기 자녀 child_id 인지 확인. 아니면 404 (정보 노출 회피)."""
    result = await session.execute(
        select(ParentChild).where(
            ParentChild.parent_id == user.id,
            ParentChild.child_id == child_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return child_id


async def require_device_token(
    x_device_token: Optional[str] = Header(default=None, alias="X-Device-Token"),
) -> None:
    """robot-web 등 디바이스 전용 endpoint — 헤더 X-Device-Token 검증."""
    if not x_device_token or x_device_token != settings.robot_device_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid device token")
