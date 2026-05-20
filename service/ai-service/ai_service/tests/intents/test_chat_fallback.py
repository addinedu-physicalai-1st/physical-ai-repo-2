"""ChatFallbackHandler — 어떤 규칙도 매치 안 됐을 때 LLM 호출."""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from ai_service.hub import Chat
from ai_service.intents.common.chat_fallback import ChatFallbackHandler
from ai_service.tests.intents.conftest import make_ctx, make_req


async def test_chat_fallback_calls_llm() -> None:
    text = "너 이름이 뭐야?"
    with (
        patch(
            "ai_service.intents.common.chat_fallback.build_chat_context",
            new_callable=AsyncMock,
        ) as _ctx_fn,
        patch(
            "ai_service.intents.common.chat_fallback.fetch_registered_children_labels",
            new_callable=AsyncMock,
        ) as _ro,
        patch(
            "ai_service.intents.common.chat_fallback.generate_chat",
            new_callable=AsyncMock,
        ) as _gen,
    ):
        _ctx_fn.return_value = {}
        _ro.return_value = None
        _gen.return_value = {"reply": "고고핑이에요!", "emotion": "happy"}
        r = await ChatFallbackHandler().try_handle(
            make_req(text, robot="gogoping"), make_ctx(text, robot="gogoping")
        )
    assert isinstance(r, Chat)
    assert "고고핑" in r.reply
    assert r.emotion == "happy"


async def test_chat_fallback_returns_teacher_line_on_timeout() -> None:
    text = "어려운 질문"

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.3)
        return {"reply": "늦은 답", "emotion": "happy"}

    with (
        patch(
            "ai_service.intents.common.chat_fallback.ai_settings.voice_chat_llm_max_wait_s",
            0.1,
        ),
        patch(
            "ai_service.intents.common.chat_fallback.build_chat_context",
            new_callable=AsyncMock,
        ) as _ctx_fn,
        patch(
            "ai_service.intents.common.chat_fallback.fetch_registered_children_labels",
            new_callable=AsyncMock,
        ) as _ro,
        patch(
            "ai_service.intents.common.chat_fallback.generate_chat",
            side_effect=slow,
        ),
    ):
        _ctx_fn.return_value = {}
        _ro.return_value = None
        r = await ChatFallbackHandler().try_handle(
            make_req(text, robot="gogoping"), make_ctx(text, robot="gogoping")
        )
    assert isinstance(r, Chat)
    assert "모르겠" in r.reply and "선생님" in r.reply
    assert r.emotion == "basic"
