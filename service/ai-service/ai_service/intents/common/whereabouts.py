"""'OOO 어딨어?' → DB 등하원 빠른 응답."""
from __future__ import annotations

from typing import ClassVar

from ai_service.capabilities import db_attendance
from ai_service.hub import Chat, IntentRequest
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse


class WhereaboutsHandler(IntentHandler):
    name: ClassVar[str] = "whereabouts"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        reply = await db_attendance.try_whereabouts_first_reply(req.text)
        if reply is None:
            return None
        return Chat(reply=reply, emotion="interest")
