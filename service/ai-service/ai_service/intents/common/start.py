"""'시작'/'출발'/'스타트' 류 발화 → SubCommand(action='start').

클라이언트의 현재 mode 컴포넌트가 useModeIntents 의 onStart handler 로 처리한다
(예: 무궁화꽃이 피었습니다 의 참가자 등록 단계 → 게임 진행).
"""
from __future__ import annotations

import re
from typing import ClassVar

from ai_service.hub import IntentRequest, SubCommand
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse

_START_KEYWORDS: tuple[str, ...] = (
    "시작",
    "시작해",
    "시작하자",
    "출발",
    "스타트",
    "고고",
    # 건너뛰기 류
    "건너뛰기",
    "건너뛰자",
    "건너뛰어",
    "건너뛰",
    "넘어가",
    "바로시작",
    "바로해",
    "바로",
    # 준비 완료 응답
    "준비됐",
    "준비됬",
    "준비완료",
    "준비됨",
    "다됐어",
    "다됐",
    # 다시 시작 (end stage 등) — '다시' 단독은 false positive 위험으로 제외.
    "다시하기",
    "다시해",
    "다시시작",
    "재시작",
    "한번더",
)


def _strip_spaces(s: str) -> str:
    return re.sub(r"\s+", "", s)


class StartHandler(IntentHandler):
    name: ClassVar[str] = "start"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        text = _strip_spaces(req.text.strip())
        if not text:
            return None
        for kw in _START_KEYWORDS:
            if kw in text:
                return SubCommand(action="start")
        return None
