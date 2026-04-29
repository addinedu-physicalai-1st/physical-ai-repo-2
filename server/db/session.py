"""비동기 SQLAlchemy 엔진 + 세션 팩토리."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.control.config import settings

engine = create_async_engine(settings.database_url, echo=False, future=True)

async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — 요청마다 세션 1개."""
    async with async_session_maker() as session:
        yield session
