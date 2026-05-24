"""Generic confirm flow — 클라가 startConfirm 호출 시 awaiting_confirm=True 로
서버에 동기화. 사용자 답을 confirm_yes / confirm_no / other 로 분류.

흐름:
  1. 클라가 voiceController.startConfirm({prompt, onConfirm, onCancel}) 호출 →
     voice store 의 confirm ref 설정 + DC msg 'awaiting_confirm_set' 송신 +
     TTS prompt + forceWake.
  2. 다음 사용자 발화의 STT 결과가 본 핸들러를 통과 (pipeline 상단).
  3. 키워드 fast path → 매치 실패 시 LLM 3-way classifier → 'confirm'/'cancel'/'other'.
  4. 'other' 분류면 다음 핸들러 (ChatFallback) 에 위임.
"""
from __future__ import annotations

import json
import logging
import re
from typing import ClassVar, Literal

from ai_service.config import settings
from ai_service.hub import ConfirmNo, ConfirmYes, IntentRequest
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse
from ai_service.llm import LLMError, _ollama_chat

logger = logging.getLogger(__name__)

_CONFIRM_KEYWORDS: tuple[str, ...] = (
    "응", "네", "예", "그래", "맞아", "오케이", "오케",
    "좋아", "좋다", "재생", "시작", "하자", "그렇",
)
_CANCEL_KEYWORDS: tuple[str, ...] = (
    "아니", "취소", "다른", "싫", "별로", "안할", "안해", "말고", "다음",
)

_SYSTEM_PROMPT = (
    "유치원 교실에서 아이가 로봇의 확인 질문에 답한 발화를 분류한다.\n"
    "출력은 JSON 한 줄: {\"intent\": \"confirm\" | \"cancel\" | \"other\"}.\n"
    "- confirm: 동의·긍정 (예: \"응\", \"좋아\", \"하자\", \"그렇게 해\").\n"
    "- cancel: 거절·다른 거 요청 (예: \"아니\", \"별로\", \"다른 거 할래\", \"다음으로\").\n"
    "- other: 위 둘 다 아닌 자유발화 (예: 무관 질문, 곡명 직접 발화).\n"
    "확신 없으면 other."
)


async def _classify_with_llm(text: str) -> Literal["confirm", "cancel", "other"]:
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    try:
        raw = await _ollama_chat(
            messages=messages,
            num_predict=32,
            num_ctx=512,
            temperature=0.0,
            model=settings.ollama_chat_model,
            timeout_s=2.5,
        )
    except LLMError as exc:
        logger.warning("confirm LLM 실패: %s", exc)
        return "other"
    try:
        data = json.loads(raw)
        intent = data.get("intent")
        if intent in ("confirm", "cancel", "other"):
            return intent  # type: ignore[return-value]
    except (json.JSONDecodeError, AttributeError):
        pass
    return "other"


def _fast_match(text: str) -> Literal["confirm", "cancel", None]:
    """cancel 키워드 먼저 — '취소해' 처럼 confirm-like 어미가 붙어도 명시적
    거절 표현이 있으면 cancel."""
    n = re.sub(r"[\s.,!?]", "", text)
    if not n:
        return None
    for w in _CANCEL_KEYWORDS:
        if w in n:
            return "cancel"
    for w in _CONFIRM_KEYWORDS:
        if w in n:
            return "confirm"
    return None


class ConfirmHandler(IntentHandler):
    name: ClassVar[str] = "confirm"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        if not req.awaiting_confirm:
            return None
        text = req.text.strip()
        if not text:
            return None
        fast = _fast_match(text)
        if fast == "confirm":
            return ConfirmYes()
        if fast == "cancel":
            return ConfirmNo()
        result = await _classify_with_llm(text)
        if result == "confirm":
            return ConfirmYes()
        if result == "cancel":
            return ConfirmNo()
        return None  # other → ChatFallback
