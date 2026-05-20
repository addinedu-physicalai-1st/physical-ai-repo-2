"""노리암 (noriarm) 전용 프롬프트.

공통 본문은 `shared_chat_system` 의 BASE_CHAT_SYSTEM / BASE_CHAT_FEW_SHOT 를 사용.
로봇별 페르소나·예시 차이는 PERSONA_HINT / EXTRA_FEW_SHOT 로 표현한다 (현재 미사용 슬롯 포함).
"""
from __future__ import annotations

from ai_service.prompts.shared_chat_system import BASE_CHAT_FEW_SHOT, BASE_CHAT_SYSTEM

DISPLAY_NAME = "노리암"
CHAT_SYSTEM = BASE_CHAT_SYSTEM
CHAT_FEW_SHOT = BASE_CHAT_FEW_SHOT
EXTRA_FEW_SHOT: list[tuple[str, dict[str, str]]] = []

PERSONA_HINT = (
    "노리암은 교실 책상에 자리 잡고 블럭쌓기·OX 퀴즈를 함께 하는 책상친구예요. "
    "차분하고 호기심 많은 말투로 같이 생각해 보자고 권해요."
)
