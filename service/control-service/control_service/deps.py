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


def _make_require_teacher_or_device_token():
    """교사 세션 쿠키 또는 X-Device-Token 헤더 둘 중 하나라도 통과하면 OK.

    fastapi_users.current_user(optional=True) 를 FastAPI DI 체인으로 사용해야
    테스트의 get_session override 가 정상 동작한다 (모듈 import 시점에 해석되면
    override 무력화).
    """
    from control_service.auth import fastapi_users
    optional_user = fastapi_users.current_user(active=True, optional=True)

    async def _dep(
        x_device_token: Optional[str] = Header(default=None, alias="X-Device-Token"),
        user: Optional[User] = Depends(optional_user),
    ) -> dict:
        if x_device_token and x_device_token == settings.robot_device_token:
            return {"actor": "device", "user": None}
        if user is not None and user.role == "teacher":
            return {"actor": "teacher", "user": user}
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Auth required")

    return _dep


require_teacher_or_device_token = _make_require_teacher_or_device_token()
