"""HelloHandler — '안녕' 단독 입력 → 시간대별 인사."""
from datetime import datetime

import pytest

from ai_service.hub import Chat
from ai_service.intents import IntentContext
from ai_service.intents.common.hello import HelloHandler
from ai_service.tests.intents.conftest import make_req


@pytest.mark.parametrize(
    "hour,expected_substr",
    [(10, "좋은 아침"), (17, "안녕히 가세요"), (14, "오늘도 만나서")],
)
async def test_hello_time_window(hour: int, expected_substr: str) -> None:
    req = make_req("안녕")
    now = datetime(2026, 5, 20, hour, 0, 0)
    ctx = IntentContext(now=now, req=req)
    r = await HelloHandler().try_handle(req, ctx)
    assert isinstance(r, Chat)
    assert expected_substr in r.reply
    assert r.emotion == "hello"


async def test_hello_passes_through_other_text() -> None:
    req = make_req("안녕 잘 지냈어?")
    from ai_service.intents import now_kst
    ctx = IntentContext(now=now_kst(), req=req)
    r = await HelloHandler().try_handle(req, ctx)
    assert r is None
