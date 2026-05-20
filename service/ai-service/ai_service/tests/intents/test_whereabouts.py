"""WhereaboutsHandler — 'OOO 어딨어?' → DB 등하원 lookup."""
from unittest.mock import AsyncMock, patch

from ai_service.hub import Chat
from ai_service.intents.common.whereabouts import WhereaboutsHandler
from ai_service.tests.intents.conftest import make_ctx, make_req


async def test_whereabouts_matches() -> None:
    text = "민준이 어딨어?"
    with patch(
        "ai_service.capabilities.db_attendance.try_whereabouts_first_reply",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = "민준이는 9시 5분에 등원했어요."
        r = await WhereaboutsHandler().try_handle(make_req(text), make_ctx(text))
    assert isinstance(r, Chat)
    assert "민준" in r.reply
    assert r.emotion == "interest"


async def test_whereabouts_passes_through_when_no_match() -> None:
    text = "오늘 날씨"
    with patch(
        "ai_service.capabilities.db_attendance.try_whereabouts_first_reply",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = None
        r = await WhereaboutsHandler().try_handle(make_req(text), make_ctx(text))
    assert r is None
