"""테스트 fixture — 별도 test DB 사용, 함수마다 transaction rollback."""
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.control.config import settings


# ---- 세션 스코프: test DB drop/create + 테이블 생성 1회 ----

@pytest_asyncio.fixture(scope="session")
async def setup_test_db():
    """test DB 를 매 세션마다 drop/create + metadata.create_all."""
    admin_url = settings.database_url.rsplit("/", 1)[0] + "/postgres"
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")

    test_db_name = settings.test_database_url.rsplit("/", 1)[1]

    async with admin_engine.connect() as conn:
        await conn.execute(text(f"DROP DATABASE IF EXISTS {test_db_name}"))
        await conn.execute(text(f"CREATE DATABASE {test_db_name}"))
    await admin_engine.dispose()

    from server.db.models import Base
    engine = create_async_engine(settings.test_database_url)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    yield


# ---- 함수 스코프: AsyncSession with savepoint rollback ----

@pytest_asyncio.fixture
async def db_session(setup_test_db) -> AsyncGenerator[AsyncSession, None]:
    """함수마다 새 connection + transaction → 끝에 rollback.
    join_transaction_mode="create_savepoint" 으로 session.commit() 이 외부 트랜잭션을 닫지 않음.
    """
    engine = create_async_engine(settings.test_database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    SessionLocal = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = SessionLocal()

    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


# ---- httpx AsyncClient with overridden DB session ----

@pytest_asyncio.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """인증 안 된 client — db_session 을 의존성 주입."""
    from server.control.main import app
    from server.db.session import get_session

    async def _override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---- factory fixture: 사용자 생성 ----

@pytest_asyncio.fixture
async def make_user(db_session):
    """User 직접 INSERT (UserManager 거치지 않음 — 빠름)."""
    from fastapi_users.password import PasswordHelper
    from server.db.models import User

    helper = PasswordHelper()

    async def _make(
        email: str,
        password: str = "test1234",
        role: str = "teacher",
        name: str = "테스터",
        phone: str | None = None,
    ) -> User:
        user = User(
            id=uuid.uuid4(),
            email=email,
            hashed_password=helper.hash(password),
            is_active=True,
            is_verified=True,
            is_superuser=False,
            role=role,
            name=name,
            phone=phone,
        )
        db_session.add(user)
        await db_session.flush()
        return user

    return _make


@pytest_asyncio.fixture
async def teacher_client(client, make_user) -> AsyncClient:
    """teacher 로그인된 client."""
    await make_user("teacher@test.com", "test1234", role="teacher", name="김선생")
    response = await client.post(
        "/api/auth/cookie/login",
        data={"username": "teacher@test.com", "password": "test1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 204, response.text
    return client


@pytest_asyncio.fixture
async def parent_client(client, make_user) -> AsyncClient:
    """parent 로그인된 client."""
    await make_user("parent@test.com", "test1234", role="parent", name="김부모")
    response = await client.post(
        "/api/auth/cookie/login",
        data={"username": "parent@test.com", "password": "test1234"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 204, response.text
    return client
