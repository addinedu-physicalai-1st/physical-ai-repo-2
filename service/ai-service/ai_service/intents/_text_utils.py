"""핸들러 공용 텍스트 정규화."""
from __future__ import annotations

import re

from ai_service.robots import name_aliases_for


def strip_robot_name(text: str, robot: str) -> str:
    """발화 앞/뒤에 붙은 로봇 이름 (+ 호격 조사 아/야, 쉼표) 제거.

    한국어 호격 조사 중 "아"/"야" 만 사용. "이"/"님"/"씨" 는 주격·일반명사 등으로
    모호하므로 제외 ("에듀핑이 좋아" 같은 평서문이 잘리는 것 방지).
    매칭 안 되면 원본 그대로 반환.
    """
    out = text.strip()
    if not out:
        return out
    aliases = name_aliases_for(robot)
    if not aliases:
        return out
    pattern = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
    # 앞쪽: 로봇 이름 (+ 옵션 아/야) + 공백/쉼표
    out = re.sub(
        rf"^({pattern})(?:[아야])?[\s,]+", "", out, count=1, flags=re.IGNORECASE
    ).strip()
    # 뒤쪽: 공백/쉼표 + 로봇 이름 + 끝 (옵션 구두점)
    out = re.sub(
        rf"[\s,]+({pattern})\s*[!?.]*\s*$", "", out, count=1, flags=re.IGNORECASE
    ).strip()
    return out
