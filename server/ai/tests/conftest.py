"""AnyIO 테스트는 asyncio 만 사용한다.

기본 anyio pytest 플러그인은 trio 가 설치되어 있으면 같은 코루틴 테스트를
`[asyncio]` / `[trio]` 로 두 번 돌린다. `httpx.AsyncClient` 는 asyncio 전용이라
trio 쪽 teardown 에서 `RuntimeError: Event loop is closed` 가 날 수 있다.
"""
import pytest


@pytest.fixture(scope="module", params=["asyncio"])
def anyio_backend(request: pytest.FixtureRequest) -> str:
    return request.param
