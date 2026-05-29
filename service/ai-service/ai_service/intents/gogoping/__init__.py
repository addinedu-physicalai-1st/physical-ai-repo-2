"""GogoPing intent dispatcher 진입점.

`match_follow_voice_intent` 는 정형 명령 ("고고핑 추종 위치확인" / "위치이동") 의 fast-path —
voice_intent 디스패처가 LLM 호출 전 우선 호출.
"""
from ai_service.intents.gogoping.follow_voice import match_follow_voice_intent

__all__ = ["match_follow_voice_intent"]
