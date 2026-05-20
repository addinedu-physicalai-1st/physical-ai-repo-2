"""'안녕' 류 인사 → 시간대별 응답.

발화 앞/뒤에 로봇 이름 (+ 호격 조사 아/야) 가 붙어 있으면 떼어내고 매칭한다.
예: "에듀핑 안녕", "에듀핑아 안녕", "안녕 에듀핑" → 모두 인사로 처리.
"""
from __future__ import annotations

from typing import ClassVar

from ai_service.hub import Chat, IntentRequest
from ai_service.intents._text_utils import strip_robot_name
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse

_GREETINGS = frozenset(
    {"안녕", "안녕!", "안녕.", "안녕하세요", "안녕하세요!", "안녕하세요."}
)


class HelloHandler(IntentHandler):
    name: ClassVar[str] = "hello"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        text = req.text.strip()
        if text not in _GREETINGS and strip_robot_name(text, req.robot) not in _GREETINGS:
            return None
        hour = ctx.now.hour
        if 9 <= hour <= 11:
            reply = "안녕하세요! 좋은 아침이에요! 어서오세요!"
        elif 16 <= hour <= 18:
            reply = "안녕히 가세요! 다음에 또 봐요!"
        else:
            reply = "안녕하세요! 오늘도 만나서 반가워요."
        return Chat(reply=reply, emotion="hello")
