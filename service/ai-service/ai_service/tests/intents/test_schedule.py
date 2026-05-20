"""ScheduleHandler — 일과표 키워드 → 빠른 응답."""
from unittest.mock import patch

from ai_service.hub import Chat
from ai_service.intents.common.schedule import ScheduleHandler
from ai_service.tests.intents.conftest import make_ctx, make_req


async def test_schedule_matches() -> None:
    text = "일과표 알려줘"
    with patch(
        "ai_service.capabilities.schedule_file.try_schedule_first_reply"
    ) as m:
        m.return_value = "일과표는: 등원 9시, 점심 12시"
        r = await ScheduleHandler().try_handle(make_req(text), make_ctx(text))
    assert isinstance(r, Chat)
    assert "일과표" in r.reply
    assert r.emotion == "hello"


async def test_schedule_passes_through_when_no_match() -> None:
    text = "오늘 날씨"
    with patch(
        "ai_service.capabilities.schedule_file.try_schedule_first_reply"
    ) as m:
        m.return_value = None
        r = await ScheduleHandler().try_handle(make_req(text), make_ctx(text))
    assert r is None
