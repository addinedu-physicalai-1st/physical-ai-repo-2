"""GenderHandler — 성별 질문 → 고정 응답."""
from ai_service.hub import Chat
from ai_service.intents.common.gender import GenderHandler
from ai_service.tests.intents.conftest import make_ctx, make_req


async def test_gender_question_matched() -> None:
    text = "너 성별이 뭐야?"
    r = await GenderHandler().try_handle(make_req(text), make_ctx(text))
    assert isinstance(r, Chat)
    assert "남자아이" in r.reply
    assert r.emotion == "happy"


async def test_gender_passes_through_other_text() -> None:
    r = await GenderHandler().try_handle(make_req("점심 메뉴"), make_ctx("점심 메뉴"))
    assert r is None
