"""정지 발화 → SubCommand(stop). 모든 로봇에서 최우선."""
from __future__ import annotations

from typing import ClassVar

from ai_service.hub import IntentRequest, SubCommand
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse
from ai_service.robots import STOP_TOKENS


def _is_stop_text(text: str) -> bool:
    lower = text.lower()
    return any(tok in lower for tok in [t.lower() for t in STOP_TOKENS])


class StopHandler(IntentHandler):
    name: ClassVar[str] = "stop"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        text = req.text.strip()
        if _is_stop_text(text):
            return SubCommand(action="stop")
        return None
