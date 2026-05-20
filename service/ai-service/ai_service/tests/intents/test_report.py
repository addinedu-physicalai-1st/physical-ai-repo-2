"""ReportHandler — 보고서·일과 + 원아 이름 → DB report lookup."""
from unittest.mock import AsyncMock, patch

from ai_service.hub import Chat
from ai_service.intents.common.report import ReportHandler
from ai_service.tests.intents.conftest import make_ctx, make_req


async def test_report_matches() -> None:
    text = "민준이 알림장 보여줘"
    with patch(
        "ai_service.capabilities.db_report.try_report_first_reply",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = "민준이는 오늘 친구들과 잘 놀았어요."
        r = await ReportHandler().try_handle(make_req(text), make_ctx(text))
    assert isinstance(r, Chat)
    assert "민준" in r.reply
    assert r.emotion == "interest"


async def test_report_passes_through_when_no_match() -> None:
    text = "오늘 날씨"
    with patch(
        "ai_service.capabilities.db_report.try_report_first_reply",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = None
        r = await ReportHandler().try_handle(make_req(text), make_ctx(text))
    assert r is None
