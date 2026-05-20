"""모드 키워드 발견 → ModeChange (LLM 우회)."""
from __future__ import annotations

from typing import ClassVar

from ai_service.hub import IntentRequest, ModeChange
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse
from ai_service.robots import modes_for


class ModeChangeHandler(IntentHandler):
    name: ClassVar[str] = "mode_change"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        text = req.text.strip()
        for m in modes_for(req.robot):
            if m in text:
                return ModeChange(mode=m)
        return None
