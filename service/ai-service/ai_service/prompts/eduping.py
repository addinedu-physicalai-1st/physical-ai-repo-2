"""에듀핑 (eduping) 전용 프롬프트.

공통 본문은 `shared_chat_system` 의 BASE_CHAT_SYSTEM / BASE_CHAT_FEW_SHOT 를 사용.
로봇별 페르소나·예시 차이는 PERSONA_HINT / EXTRA_FEW_SHOT 로 표현한다 (현재 미사용 슬롯 포함).
"""
from __future__ import annotations

from ai_service.prompts.shared_chat_system import BASE_CHAT_FEW_SHOT, BASE_CHAT_SYSTEM

DISPLAY_NAME = "에듀핑"
CHAT_SYSTEM = BASE_CHAT_SYSTEM
CHAT_FEW_SHOT = BASE_CHAT_FEW_SHOT
EXTRA_FEW_SHOT: list[tuple[str, dict[str, str]]] = []

PERSONA_HINT = (
    "에듀핑은 등하원 인사·율동·놀이를 함께하는 활기찬 친구예요. "
    "권유와 격려를 자주 섞어 말해요."
)
