"""AttendanceHandler — 이름 단독 입력 → 등하원 규칙 답변."""
from unittest.mock import AsyncMock, patch

from ai_service.hub import Chat
from ai_service.intents.common.attendance import AttendanceHandler
from ai_service.tests.intents.conftest import make_ctx, make_req


async def test_attendance_matches() -> None:
    text = "민준"
    with patch(
        "ai_service.capabilities.db_attendance.try_attendance_first_reply",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = "민준이는 9시 5분에 등원했어요."
        r = await AttendanceHandler().try_handle(make_req(text), make_ctx(text))
    assert isinstance(r, Chat)
    assert r.emotion == "hello"


async def test_attendance_passes_through_when_no_match() -> None:
    text = "오늘 날씨"
    with patch(
        "ai_service.capabilities.db_attendance.try_attendance_first_reply",
        new_callable=AsyncMock,
    ) as m:
        m.return_value = None
        r = await AttendanceHandler().try_handle(make_req(text), make_ctx(text))
    assert r is None
