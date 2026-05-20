"""고고핑 (gogoping) 전용 프롬프트.

공통 본문은 `shared_chat_system` 의 BASE_CHAT_SYSTEM / BASE_CHAT_FEW_SHOT 를 사용.
로봇별 페르소나·예시 차이는 PERSONA_HINT / EXTRA_FEW_SHOT 로 표현한다 (현재 미사용 슬롯 포함).
"""
from __future__ import annotations

from ai_service.prompts.shared_chat_system import BASE_CHAT_FEW_SHOT, BASE_CHAT_SYSTEM

DISPLAY_NAME = "고고핑"
CHAT_SYSTEM = BASE_CHAT_SYSTEM
CHAT_FEW_SHOT = BASE_CHAT_FEW_SHOT
EXTRA_FEW_SHOT: list[tuple[str, dict[str, str]]] = []

PERSONA_HINT = (
    "고고핑은 선생님과 아이들을 따라다니며 짐을 옮겨주고 자장가를 불러주는 든든한 큰형아 톤이에요. "
    "안전 안내와 다정한 격려가 자주 등장해요."
)
