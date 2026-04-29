"""fastapi-users 설정 — UserManager + cookie backend + UserRead/UserUpdate."""
import uuid
from collections.abc import AsyncGenerator
from typing import Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, InvalidPasswordException, UUIDIDMixin
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import AccessTokenDatabase, DatabaseStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from fastapi_users.schemas import BaseUser, BaseUserCreate, BaseUserUpdate
from sqlalchemy.ext.asyncio import AsyncSession

from server.control.config import settings
from server.db.models import AccessToken, User
from server.db.session import get_session


# ---- Pydantic 스키마 ----

class UserRead(BaseUser[uuid.UUID]):
    role: str
    name: str
    phone: str | None = None


class UserCreate(BaseUserCreate):
    role: str
    name: str
    phone: str | None = None


class UserUpdate(BaseUserUpdate):
    name: str | None = None
    phone: str | None = None
    current_password: str | None = None


# ---- DB 어댑터 ----

async def get_user_db(session: AsyncSession = Depends(get_session)):
    yield SQLAlchemyUserDatabase(session, User)


async def get_access_token_db(session: AsyncSession = Depends(get_session)):
    yield SQLAlchemyAccessTokenDatabase(session, AccessToken)


# ---- UserManager ----

class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = settings.secret
    verification_token_secret = settings.secret

    async def validate_password(self, password: str, user) -> None:
        if len(password) < 8:
            raise InvalidPasswordException(reason="Password should be at least 8 characters")

    async def _update(self, user: User, update_dict: dict) -> User:
        """비밀번호 변경 시 current_password 검증 + dict 정제."""
        if "password" in update_dict:
            current = update_dict.get("current_password")
            if not current:
                raise InvalidPasswordException(reason="current_password required")
            verified, _ = self.password_helper.verify_and_update(
                current, user.hashed_password
            )
            if not verified:
                raise InvalidPasswordException(reason="current_password invalid")

        # current_password 는 User 모델 필드가 아니므로 제거 후 super 위임
        update_dict.pop("current_password", None)
        return await super()._update(user, update_dict)


async def get_user_manager(user_db=Depends(get_user_db)) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)


# ---- 인증 백엔드 (cookie + DatabaseStrategy) ----

cookie_transport = CookieTransport(
    cookie_name="session",
    cookie_max_age=settings.cookie_max_age,
    cookie_httponly=True,
    cookie_samesite="lax",
    cookie_secure=False,  # dev — production HTTPS 시 True
)


def get_database_strategy(
    access_token_db: AccessTokenDatabase = Depends(get_access_token_db),
) -> DatabaseStrategy:
    return DatabaseStrategy(access_token_db, lifetime_seconds=settings.cookie_max_age)


cookie_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_database_strategy,
)


# ---- FastAPIUsers ----

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [cookie_backend])

current_active_user = fastapi_users.current_user(active=True)
