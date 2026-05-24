"""율동 모드 컨텍스트 인지 intent — RhythmPlay(곡 재생) / RhythmStop(음악 정지).

eduping 율동 모드 안에서만 활성 (req.mode == '율동'). 다른 모드에서는 양쪽 모두 None
반환하여 ModeChange/Stop/ChatFallback 등 일반 핸들러로 위임한다.

곡명 fuzzy 매칭은 ai-service 가 control-service 의 dance 라이브러리에 직접 접근하지
않으므로 여기서는 raw 추출만 — verb 앞/뒤의 비-verb 부분을 song 후보로 client 에
넘기고 (DancePlayPopup) 그쪽에서 등록된 slug 와 정규화 매칭.
"""
from __future__ import annotations

import re
from typing import ClassVar

from ai_service.hub import IntentRequest, RhythmPlay, RhythmStop
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse

_RHYTHM_MODE = "율동"

# play 동사 — 발화 안에 하나라도 있으면 RhythmPlay 후보. 우선순위 없음 (longest-match 도
# 굳이 필요 없는 짧은 키워드들).
_PLAY_VERBS: tuple[str, ...] = (
    "틀어줘",
    "들려줘",
    "재생",
    "틀어",
    "들려",
    "켜줘",
    "켜",
)

# stop 키워드 — '그만'/'멈춰' 류. '노래'/'음악' 한정어가 같이 들어가야 RhythmStop 으로
# 본다. 한정어 없으면 일반 stop 으로 처리해서 모드 자체를 빠져나가게 (StopHandler).
_STOP_VERBS: tuple[str, ...] = ("멈춰", "그만", "정지", "스톱", "스탑", "중지")
_STOP_QUALIFIERS: tuple[str, ...] = ("노래", "음악", "곡")

# 발화에서 song 후보 추출용 — robot 이름 + play verb + 한정어 ('노래' 등) 제거.
_STRIP_TOKENS: tuple[str, ...] = (
    "에듀핑아",
    "에듀핑",
    "에듀핀",
    "애듀핑",
    "애듀핀",
    "에듀팽",
    "에듀빙",
    "이거",
    "이",
    "그거",
    "그",
    "좀",
    "다시",
    "다음",
    "노래",
    "음악",
    "곡",
    "율동",
    "로",
    "을",
    "를",
    "은",
    "는",
    "이",
    "가",
    # 흔한 chat 패턴 — song 후보에서 제거되어 빈 결과면 None 반환 → ignored.
    "안녕",
    "안녕하세요",
    "안녕히",
    "반가워",
    "잘있어",
    "고마워",
    "감사",
    "사랑해",
)


_PUNCT_STRIP = ".,!?。｡"


def _extract_song(text: str) -> str:
    """play verb 와 한정어 / robot 명 제거 후 남는 부분을 song 후보로.

    STT 가 종종 문장 끝에 '.' 을 붙이므로 각 토큰의 양끝 punctuation 도 떼어낸다.
    """
    cleaned = text
    for v in _PLAY_VERBS:
        cleaned = cleaned.replace(v, " ")
    # token 제거 — 띄어쓰기 단위, 각 토큰의 punctuation 도 strip.
    parts = [p.strip(_PUNCT_STRIP) for p in re.split(r"\s+", cleaned)]
    parts = [p for p in parts if p and p not in _STRIP_TOKENS]
    return " ".join(parts).strip()


class RhythmStopHandler(IntentHandler):
    name: ClassVar[str] = "rhythm_stop"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        if req.mode != _RHYTHM_MODE:
            return None
        text = req.text.strip()
        if not any(v in text for v in _STOP_VERBS):
            return None
        # '노래/음악/곡' 한정어가 있어야 RhythmStop. 없으면 StopHandler 가 잡도록
        # None 반환 — 모드 자체를 종료하는 일반 stop 으로 처리.
        if not any(q in text for q in _STOP_QUALIFIERS):
            return None
        return RhythmStop()


# 발화가 너무 길면 (자유 chat 으로 추정) verb 없이는 잡지 않는다 — 곡명은 보통
# 1~2 단어. 이 임계를 넘는 long 발화 + verb 없음 = ChatFallback 으로 위임.
_MAX_SONG_TOKENS_WITHOUT_VERB = 2

# 질문/대화 패턴 — 들어가면 곡명 후보로 안 봄.
_QUESTION_MARKERS: tuple[str, ...] = (
    "뭐야",
    "뭐예요",
    "뭐",
    "누구",
    "어디",
    "왜",
    "어떻게",
    "?",
)


class RhythmPlayHandler(IntentHandler):
    """율동 모드 컨텍스트 한정 — verb 가 있거나 짧은 곡명 후보면 RhythmPlay.

    파이프라인에서 ChatFallback 직전에 위치시키는 게 핵심. 다른 룰 핸들러
    (Stop/Hello/ModeChange 등) 가 먼저 잡고, 그래도 안 잡힌 자유발화 중
    곡명으로 보이는 것만 흡수.
    """
    name: ClassVar[str] = "rhythm_play"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        if req.mode != _RHYTHM_MODE:
            return None
        text = req.text.strip()
        if not text:
            return None
        # 질문/대화 패턴이 들어가면 ChatFallback 으로 위임.
        if any(q in text for q in _QUESTION_MARKERS):
            return None
        has_verb = any(v in text for v in _PLAY_VERBS)
        song = _extract_song(text)
        if not song:
            return None
        # verb 없으면 짧은 곡명 후보만 통과. 긴 자유발화는 ChatFallback 으로.
        if not has_verb:
            token_count = len([t for t in re.split(r"\s+", song) if t])
            if token_count > _MAX_SONG_TOKENS_WITHOUT_VERB:
                return None
        # ai-service 는 라이브러리 모르므로 song slug 결정 못 함 — display_name 만
        # 채우고 slug 는 client 가 라이브러리 매칭 후 확정.
        return RhythmPlay(song="", display_name=song)
