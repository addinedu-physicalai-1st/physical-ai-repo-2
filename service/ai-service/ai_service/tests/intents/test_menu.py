"""MenuHandler — 점심·메뉴·급식 + 날짜 마커 → DB 조회 → Chat."""
from unittest.mock import AsyncMock, patch

from ai_service.hub import Chat
from ai_service.intents.common.menu import MenuHandler
from ai_service.tests.intents.conftest import make_ctx, make_req


async def test_menu_matches_today_menu() -> None:
    req = make_req("오늘 점심 메뉴 뭐야?")
    ctx = make_ctx("오늘 점심 메뉴 뭐야?")
    with patch(
        "ai_service.capabilities.db_menu.get_menu_fast", new_callable=AsyncMock
    ) as m:
        m.return_value = "오늘 점심은 단위테스트밥!"
        r = await MenuHandler().try_handle(req, ctx)
    assert isinstance(r, Chat)
    assert "단위테스트밥" in r.reply
    assert r.emotion == "happy"


async def test_menu_passes_through_non_menu_text() -> None:
    req = make_req("안녕")
    ctx = make_ctx("안녕")
    r = await MenuHandler().try_handle(req, ctx)
    assert r is None
