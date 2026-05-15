"""DB 연결 검증 — postgres 가 떠있어야 함."""
import pytest
from sqlalchemy import text

from control_db.session import async_session_maker


pytestmark = pytest.mark.asyncio


async def test_can_connect_to_postgres():
    async with async_session_maker() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1


async def test_can_query_postgres_version():
    async with async_session_maker() as session:
        result = await session.execute(text("SHOW server_version"))
        version = result.scalar()
        assert version is not None
        # PostgreSQL 17.x 검증
        assert version.startswith("17."), f"expected PG 17, got {version}"
