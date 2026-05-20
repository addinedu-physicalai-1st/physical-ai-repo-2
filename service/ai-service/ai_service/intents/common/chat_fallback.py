"""규칙 매치 실패 시 최종 fallback — LLM 호출 + 안전 가드.

이 핸들러는 절대 None 을 반환하지 않는다 (디스패처 invariant).
LLM 실패·timeout 시에도 안전 문구를 반환한다.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import ClassVar

from ai_service import prompts
from ai_service.capabilities.db_roster import fetch_registered_children_labels
from ai_service.config import settings as ai_settings
from ai_service.context import build_chat_context
from ai_service.guard_replies import teacher_idk_line
from ai_service.hub import Chat, IntentRequest
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse
from ai_service.llm import LLMError, generate_chat

logger = logging.getLogger(__name__)


def _normalize_utterance(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower())


def _needs_chat_fallback(user_text: str, reply: str) -> bool:
    u = _normalize_utterance(user_text)
    r = _normalize_utterance(reply)
    if not u or not r:
        return True
    if u == r:
        return True
    if len(r) <= max(8, len(u) + 2) and (u in r or r in u):
        return True
    return False


class ChatFallbackHandler(IntentHandler):
    name: ClassVar[str] = "chat_fallback"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        text = req.text.strip()

        # 컨텍스트 + 명단 DB 는 병렬로 가져와 레이턴시 절감
        chat_ctx: dict[str, str] = {}
        db_roster: str | None = None
        c_out, roster_out = await asyncio.gather(
            build_chat_context(text, req.robot),
            fetch_registered_children_labels(),
            return_exceptions=True,
        )
        if not isinstance(c_out, BaseException):
            chat_ctx = c_out
        if not isinstance(roster_out, BaseException):
            db_roster = roster_out
        if db_roster:
            chat_ctx["registered_children"] = db_roster
        elif req.class_roster:
            chat_ctx["registered_children"] = ", ".join(req.class_roster)

        cap = float(ai_settings.voice_chat_llm_max_wait_s or 0.0)
        try:
            if cap > 0:
                chat = await asyncio.wait_for(
                    generate_chat(text, req.robot, chat_ctx),
                    timeout=cap,
                )
            else:
                chat = await generate_chat(text, req.robot, chat_ctx)
        except asyncio.TimeoutError:
            return Chat(
                reply=teacher_idk_line(prompts.display_name(req.robot)),
                emotion="basic",
            )
        except LLMError:
            name = prompts.display_name(req.robot)
            return Chat(
                reply=f"{name}에게 잠깐 연결 문제가 생겼어요. 다시 한번 말해줄래요?",
                emotion="basic",
            )

        if _needs_chat_fallback(text, chat.get("reply", "")):
            return Chat(
                reply="알겠어요! 도와달라는 말로 이해했어요. 무엇이 필요한지 한 번만 더 말해줄래요?",
                emotion="interest",
            )
        return Chat(reply=chat["reply"], emotion=chat["emotion"])
