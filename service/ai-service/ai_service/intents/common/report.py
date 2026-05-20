"""보고서·일과 + 원아 한 명 확실 → DB report 빠른 응답."""
from __future__ import annotations

from typing import ClassVar

from ai_service.capabilities import db_report
from ai_service.hub import Chat, IntentRequest
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse


class ReportHandler(IntentHandler):
    name: ClassVar[str] = "report"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        reply = await db_report.try_report_first_reply(req.text)
        if reply is None:
            return None
        return Chat(reply=reply, emotion="interest")
