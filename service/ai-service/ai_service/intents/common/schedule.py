"""일과표·시간표 키워드 → shared JSON 빠른 응답 (LLM 보다 먼저)."""
from __future__ import annotations

from typing import ClassVar

from ai_service.capabilities import schedule_file
from ai_service.hub import Chat, IntentRequest
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse


class ScheduleHandler(IntentHandler):
    name: ClassVar[str] = "schedule"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        reply = schedule_file.try_schedule_first_reply(req.text)
        if reply is None:
            return None
        return Chat(reply=reply, emotion="hello")
