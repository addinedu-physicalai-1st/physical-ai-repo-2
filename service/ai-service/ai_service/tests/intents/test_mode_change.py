"""ModeChangeHandler — 모드 키워드 발견 → ModeChange."""
from ai_service.hub import ModeChange
from ai_service.intents.common.mode_change import ModeChangeHandler
from ai_service.tests.intents.conftest import make_ctx, make_req


async def test_mode_change_eduping_yuldong() -> None:
    text = "지금부터 율동 모드로 해줘"
    r = await ModeChangeHandler().try_handle(
        make_req(text, robot="eduping"), make_ctx(text, robot="eduping")
    )
    assert r == ModeChange(mode="율동")


async def test_mode_change_passes_through_unrelated() -> None:
    r = await ModeChangeHandler().try_handle(make_req("안녕"), make_ctx("안녕"))
    assert r is None
