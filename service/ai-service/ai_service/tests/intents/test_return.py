"""ReturnHandler — gogoping 전용 '복귀'/'충전' 발화."""
from ai_service.hub import SubCommand
from ai_service.intents.gogoping.return_ import ReturnHandler
from ai_service.tests.intents.conftest import make_ctx, make_req


async def test_return_matches() -> None:
    text = "충전소로 돌아가"
    r = await ReturnHandler().try_handle(
        make_req(text, robot="gogoping"), make_ctx(text, robot="gogoping")
    )
    assert r == SubCommand(action="return")


async def test_return_passes_through_unrelated() -> None:
    r = await ReturnHandler().try_handle(
        make_req("안녕", robot="gogoping"), make_ctx("안녕", robot="gogoping")
    )
    assert r is None


import pytest


@pytest.mark.parametrize("text", ["복귀해", "복귀", "복구해", "복기해", "제자리로", "돌아 와"])
async def test_return_variants_match(text: str) -> None:
    """복귀 STT 오인식/자연어 변형도 RETURNING 으로."""
    r = await ReturnHandler().try_handle(
        make_req(text, robot="gogoping"), make_ctx(text, robot="gogoping")
    )
    assert r == SubCommand(action="return")
