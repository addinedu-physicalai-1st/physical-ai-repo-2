"""모드 키워드 발견 → ModeChange (LLM 우회).

길이 내림차순 + alias 사전 매치 — 같은 발화에 짧은/긴 mode 키워드가
함께 들어가도 ('율동 등록' 안의 '율동') 더 긴 쪽이 먼저 잡힌다.

매치 시 양쪽 모두 공백 제거 후 비교 — STT 가 종종 다른 띄어쓰기로 떨어져
("무궁화꽃이 피었습니다" vs "무궁화 꽃이 피었습니다") substring 매치를 깨는
경우 방지.

substring 도 못 잡으면 긴 키워드 (>= 5 글자) 에 한해 char-bigram Jaccard
fuzzy match 폴백 — "동화꽃이 피었습니다" 같이 첫 음절이 누락된 STT 결과까지
흡수. 짧은 키워드 (예: '율동') 는 bigram sparse 라 false positive 위험 → fuzzy
fallback 제외.
"""
from __future__ import annotations

import re
from typing import ClassVar

from ai_service.hub import IntentRequest, ModeChange
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse
from ai_service.robots import mode_matchers_for


def _strip_spaces(s: str) -> str:
    # lower() — STT 가 'OX 퀴즈' 를 'ox 퀴즈'/'Ox 퀴즈' 로 떨어뜨려도 매치되게.
    return re.sub(r"\s+", "", s).lower()


def _bigrams(s: str) -> set[str]:
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


_FUZZY_MIN_KEYWORD_LEN = 5
_FUZZY_THRESHOLD = 0.5


class ModeChangeHandler(IntentHandler):
    name: ClassVar[str] = "mode_change"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        text_n = _strip_spaces(req.text.strip())
        if not text_n:
            return None
        # 1) substring path (공백 무시).
        for keyword, mode in mode_matchers_for(req.robot):
            if _strip_spaces(keyword) not in text_n:
                continue
            # 이미 그 모드 안에 있는데 같은 mode 키워드가 발화에 섞이면 (예:
            # 율동 모드 안에서 '민쩐 율동') 모드 재진입이 아니라 곡명/대화일 가능성
            # 더 큼 → mode_change 무시하고 다음 핸들러 (rhythm_play 등) 에 위임.
            # 단 '대기' 는 sub-content 가 없어 재진입 허용 (idle 에서 "대기 모드" 발화도 통과).
            if req.mode == mode and mode != "대기":
                continue
            return ModeChange(mode=mode)
        # 2) char-bigram Jaccard fuzzy fallback — 긴 키워드만.
        text_bigrams = _bigrams(text_n)
        best: tuple[float, str] | None = None
        for keyword, mode in mode_matchers_for(req.robot):
            key_n = _strip_spaces(keyword)
            if len(key_n) < _FUZZY_MIN_KEYWORD_LEN:
                continue
            if req.mode == mode and mode != "대기":
                continue
            sim = _jaccard(_bigrams(key_n), text_bigrams)
            if sim < _FUZZY_THRESHOLD:
                continue
            if best is None or sim > best[0]:
                best = (sim, mode)
        if best is not None:
            return ModeChange(mode=best[1])
        return None
