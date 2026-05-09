"""WS 핸드셰이크 cookie 인증.

PLAN §5.4 — fastapi-users 의 session 쿠키 검증.
[server/control/auth.py](../auth.py) 의 cookie_backend 와 같은 cookie 이름·DB 전략.

Q4 결정 (PLAN §10): fastapi-users 세션 쿠키만 사용. 별도 토큰 X.

dev 모드 토글: streaming/config.py 의 `require_auth` (env STREAMING_REQUIRE_AUTH).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket
from sqlalchemy import select

from server.control.config import settings as control_settings
from server.control.streaming.config import settings as streaming_settings
from server.db.models import AccessToken
from server.db.session import async_session_maker


_log = logging.getLogger("streaming.auth")

# dev anonymous 식별자 (require_auth=False 일 때만)
ANONYMOUS_USER_ID = "dev-anonymous"


async def authenticate_ws_session(ws: WebSocket) -> Optional[str]:
    """WS 핸드셰이크 의 session 쿠키 검증.

    Returns user_id (UUID str) if valid, None otherwise.
    require_auth=False (dev 모드) 면 cookie 유무와 무관하게 ANONYMOUS_USER_ID 반환.
    """
    if not streaming_settings.require_auth:
        # dev 모드 — 쿠키가 있으면 검증 시도, 없거나 실패해도 통과
        token = ws.cookies.get("session")
        if token:
            user_id = await _validate_token(token)
            if user_id is not None:
                return user_id
        return ANONYMOUS_USER_ID

    token = ws.cookies.get("session")
    if not token:
        return None
    return await _validate_token(token)


async def _validate_token(token: str) -> Optional[str]:
    """[server/control/auth.py](../auth.py) 의 cookie_transport 와 같은 cookie name."""
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                select(AccessToken).where(AccessToken.token == token),
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            now = datetime.now(timezone.utc)
            created = record.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age = (now - created).total_seconds()
            if age > control_settings.cookie_max_age:
                return None
            return str(record.user_id)
    except Exception as exc:
        _log.warning("session 검증 실패: %s", exc)
        return None
