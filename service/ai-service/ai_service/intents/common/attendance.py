"""원아 이름 단독 입력 → 등하원 규칙 답변 (LLM 환각 방지)."""
from __future__ import annotations

from typing import ClassVar

from ai_service.capabilities import db_attendance
from ai_service.hub import Chat, IntentRequest
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse


class AttendanceHandler(IntentHandler):
    name: ClassVar[str] = "attendance"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        reply = await db_attendance.try_attendance_first_reply(req.text)
        if reply is None:
            return None
        return Chat(reply=reply, emotion="hello")
