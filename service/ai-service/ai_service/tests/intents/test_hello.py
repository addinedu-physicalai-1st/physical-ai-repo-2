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


@pytest.mark.parametrize(
    "text,robot",
    [
        ("에듀핑 안녕", "eduping"),
        ("에듀핑아 안녕", "eduping"),
        ("에듀핑, 안녕", "eduping"),
        ("안녕 에듀핑", "eduping"),
        ("에듀핑 안녕하세요", "eduping"),
        ("고고핑 안녕", "gogoping"),
        ("노리암아 안녕", "noriarm"),
    ],
)
async def test_hello_strips_wake_name(text: str, robot: str) -> None:
    req = make_req(text, robot=robot)
    now = datetime(2026, 5, 20, 10, 0, 0)  # 오전 인사 윈도우
    ctx = IntentContext(now=now, req=req)
    r = await HelloHandler().try_handle(req, ctx)
    assert isinstance(r, Chat)
    assert r.emotion == "hello"


@pytest.mark.parametrize(
    "text,robot",
    [
        ("에듀핑이에요", "eduping"),  # 평서문 — 호격 아님
        ("에듀핑이 좋아", "eduping"),  # 주격 — 호격 아님
        ("에듀핑 점심 메뉴", "eduping"),  # 다른 intent
        ("에듀핑 안녕", "gogoping"),  # 다른 로봇 이름 — 통과
    ],
)
async def test_hello_does_not_strip_non_vocative(text: str, robot: str) -> None:
    req = make_req(text, robot=robot)
    from ai_service.intents import now_kst
    ctx = IntentContext(now=now_kst(), req=req)
    r = await HelloHandler().try_handle(req, ctx)
    assert r is None
