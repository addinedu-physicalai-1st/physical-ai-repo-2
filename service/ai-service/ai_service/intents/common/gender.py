"""성별 질문 → 고정 응답 (LLM 우회)."""
from __future__ import annotations

import re
from typing import ClassVar

from ai_service.hub import Chat, IntentRequest
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse


def _normalize_utterance(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower())


def _is_gender_question(text: str) -> bool:
    compact = _normalize_utterance(text)
    if not compact:
        return False
    gender_tokens = ("성별", "남자", "여자", "boy", "girl", "male", "female")
    ask_tokens = ("너", "로봇", "누구", "뭐")
    return any(t in compact for t in gender_tokens) and (
        any(t in compact for t in ask_tokens) or "야" in text or "인가" in text
    )


class GenderHandler(IntentHandler):
    name: ClassVar[str] = "gender"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        if not _is_gender_question(req.text):
            return None
        return Chat(
            reply="나는 남자아이처럼 말하는 로봇 친구야! 같이 재미있게 이야기하자.",
            emotion="happy",
        )
