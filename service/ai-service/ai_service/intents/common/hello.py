"""'안녕' 단독 입력 → 시간대별 인사."""
from __future__ import annotations

from typing import ClassVar

from ai_service.hub import Chat, IntentRequest
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse


class HelloHandler(IntentHandler):
    name: ClassVar[str] = "hello"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        text = req.text.strip()
        if text not in ("안녕", "안녕!"):
            return None
        hour = ctx.now.hour
        if 9 <= hour <= 11:
            reply = "안녕하세요! 좋은 아침이에요! 어서오세요!"
        elif 16 <= hour <= 18:
            reply = "안녕히 가세요! 다음에 또 봐요!"
        else:
            reply = "안녕하세요! 오늘도 만나서 반가워요."
        return Chat(reply=reply, emotion="hello")
