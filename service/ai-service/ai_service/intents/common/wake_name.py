"""로봇 이름만 단독 발화한 경우 (wake-word echo or 부름) → 친근한 ack.

ChatFallback (LLM) 까지 흘러가면 "내용 없음" 으로 판단해 선생님 안내가 나오므로,
규칙으로 가로채서 환영 응답을 한다.
"""
from __future__ import annotations

import re
from typing import ClassVar

from ai_service import prompts
from ai_service.hub import Chat, IntentRequest
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse
from ai_service.robots import name_aliases_for

# 발화 전후의 일반 구두점/공백 제거용. 한국어 조사·접미사는 일부러 제거하지 않음
# ("에듀핑아", "에듀핑이" 같은 케이스는 통과시켜 LLM 에 맡긴다).
_PUNCT_STRIP = re.compile(r"^[\s\.,!?…:;\-~]+|[\s\.,!?…:;\-~]+$")


def _stripped_lower(text: str) -> str:
    return _PUNCT_STRIP.sub("", text).lower()


class WakeNameHandler(IntentHandler):
    name: ClassVar[str] = "wake_name"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        candidate = _stripped_lower(req.text)
        if not candidate:
            return None
        if candidate not in name_aliases_for(req.robot):
            return None
        display = prompts.display_name(req.robot)
        return Chat(reply=f"네! {display} 여기 있어요. 뭐가 궁금해요?", emotion="hello")
