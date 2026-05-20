"""gogoping 전용 — '복귀' / '충전소로 돌아가' 발화."""
from __future__ import annotations

from typing import ClassVar

from ai_service.hub import IntentRequest, SubCommand
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse

_RETURN_TOKENS = ("복귀", "돌아가", "돌아와", "충전소", "충전하러", "충전 하러")


def _is_return_text(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    return any(tok in t for tok in _RETURN_TOKENS)


class ReturnHandler(IntentHandler):
    name: ClassVar[str] = "return"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        if _is_return_text(req.text):
            return SubCommand(action="return")
        return None
