"""'화내봐' '슬퍼봐' 등 감정 연기 요청 → 고정 응답.

LLM 이 이런 입력에서 엉뚱한 말을 내는 경우가 많아 규칙으로 고정.
"""
from __future__ import annotations

import re
from typing import ClassVar

from ai_service import prompts
from ai_service.hub import Chat, IntentRequest
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse


def _emotion_demo_match(text: str, robot: str) -> Chat | None:
    raw = text.strip()
    if len(raw) > 36:
        return None
    if "지마" in raw or "하지마" in raw.replace(" ", ""):
        return None
    c = re.sub(r"[\s\.,!?…:]+", "", raw)
    if not c:
        return None

    imperatives = ("봐", "줘", "해봐", "해줘", "할래", "연기", "흉내", "해줄래")
    has_imperative = any(m in raw for m in imperatives)
    if len(c) > 10 and not has_imperative:
        return None

    name = prompts.display_name(robot)

    if any(k in c for k in ("화내", "화나", "짜증", "빡쳐", "열받", "분노")):
        return Chat(reply=f"으… {name} 화났어! 금방 가라앉힐게.", emotion="angry")
    if any(k in c for k in ("슬프", "슬퍼", "우울", "서글")):
        return Chat(reply=f"흑… 너무 슬퍼. {name}이 같이 있어줄게.", emotion="sad")
    if any(k in c for k in ("울어", "눈물", "엉엉")):
        return Chat(reply=f"으응… 울어도 괜찮아. {name}이 옆에 있어줄게.", emotion="sad")
    if any(k in c for k in ("웃어", "웃자", "행복", "기뻐", "신나")):
        return Chat(reply=f"헤헤! {name}도 신나! 같이 웃자!", emotion="happy")
    if "심심" in c:
        return Chat(reply="심심해? 같이 뭐 재미있는 거 해볼까?", emotion="bored")
    if any(k in c for k in ("졸려", "잘래", "자고", "쿨쿨")):
        return Chat(reply="쿨… 잠이 와… 조금만 눈 붙일게…", emotion="sleep")
    if "재밌" in c:
        return Chat(reply="좋아! 재미있게 놀아보자!", emotion="fun")
    return None


class EmotionDemoHandler(IntentHandler):
    name: ClassVar[str] = "emotion_demo"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        return _emotion_demo_match(req.text, req.robot)
