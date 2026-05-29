"""Voice-guided search intent — STT text → FollowSearch / FollowResume.

LLM 호출 전 fast-path keyword 매칭. 매칭 안 되면 None 반환 (downstream LLM 으로).
"""
from __future__ import annotations

import re

_PATTERN_FOLLOW_SEARCH = re.compile(r"추종\s*위치\s*확인")
_PATTERN_FOLLOW_RESUME = re.compile(r"추종\s*위치\s*이동")


def match_follow_voice_intent(text: str):
    """STT text → FollowSearch / FollowResume / None.

    GogoPing 의 음성 보조 lost-recovery 명령. 정형 명령이라 LLM 거치지 않고
    정규식 매칭으로 빠르게 처리.
    """
    if _PATTERN_FOLLOW_SEARCH.search(text):
        from ai_service.hub import FollowSearch
        return FollowSearch()
    if _PATTERN_FOLLOW_RESUME.search(text):
        from ai_service.hub import FollowResume
        return FollowResume()
    return None
