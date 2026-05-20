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
