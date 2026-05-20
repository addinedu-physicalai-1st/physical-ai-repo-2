"""StopHandler — 정지 토큰 매칭 → SubCommand(stop)."""
import pytest

from ai_service.hub import SubCommand
from ai_service.intents.common.stop import StopHandler
from ai_service.tests.intents.conftest import make_ctx, make_req


@pytest.mark.parametrize("text", ["멈춰", "정지", "스톱", "그만해"])
async def test_stop_matches_stop_tokens(text: str) -> None:
    req = make_req(text)
    ctx = make_ctx(text)
    r = await StopHandler().try_handle(req, ctx)
    assert r == SubCommand(action="stop")


async def test_stop_passes_through_normal_text() -> None:
    req = make_req("점심 메뉴")
    ctx = make_ctx("점심 메뉴")
    r = await StopHandler().try_handle(req, ctx)
    assert r is None
