"""gogoping 전용 — '복귀' / '충전소로 돌아가' 발화."""
from __future__ import annotations

from typing import ClassVar

from ai_service.hub import IntentRequest, SubCommand
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse

_RETURN_TOKENS = (
    # 정식 + 자연어
    "복귀", "돌아가", "돌아와", "돌아 가", "돌아 와", "충전소", "충전하러", "충전 하러",
    "충전해", "충전 해", "제자리로",
    # 복귀 STT 오인식 변형 (받침/유사음)
    "복구", "복기", "복궈", "복위", "보귀", "봉귀", "복뀌", "복기해", "복귀해",
)


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
