"""Microsoft Edge-style neural TTS via edge-tts (internet). Korean default voice."""
from __future__ import annotations

import logging
import re
from typing import AsyncIterator

import edge_tts

from ai_service.config import settings

_HANGUL_RE = re.compile(r"[가-힣]")
_BIDI_AND_ZW_RE = re.compile(
    r"[\u202a-\u202e\u200e\u200f\u2066-\u2069\u200b-\u200d\ufeff\u00ad]"
)
_TTS_NON_KOREAN_FALLBACK = (
    "미안해요. 지금은 한국어로만 말할 수 있어요. 한국어로 다시 말해줄래요?"
)


def normalize_text_for_korean_piper(text: str) -> str:
    """TTS 입력 보정 — 방향 제어 문자 제거·비한글 과다 시 안내 문구로 치환 (Edge TTS 공통)."""
    stripped = _BIDI_AND_ZW_RE.sub("", text).strip()
    if not stripped:
        return stripped
    hangul = len(_HANGUL_RE.findall(stripped))
    compact = re.sub(r"\s+", "", stripped)
    significant = len(compact)
    if significant >= 6 and hangul == 0:
        logging.warning(
            "[edge_tts] TTS text has no Hangul; using Korean fallback line"
        )
        return _TTS_NON_KOREAN_FALLBACK
    if significant >= 28 and hangul > 0 and hangul / significant < 0.12:
        logging.warning(
            "[edge_tts] TTS text is mostly non-Hangul; using Korean fallback line"
        )
        return _TTS_NON_KOREAN_FALLBACK
    return stripped

# `Communicate` 는 입력 전체에 `xml.sax.saxutils.escape` 후 `mkssml` 로 한 겹 더 감싼다.
# 여기에 `<speak>…` 를 넣으면 태그가 이스케이프되어 **문자 그대로 읽히거나** 앞뒤 잡음처럼 들린다.
_HZ_RE = re.compile(r"^([+-])(\d+)Hz$", re.I)
_ST_RE = re.compile(r"^([+-])(\d+(?:\.\d+)?)st$", re.I)
_PCT_RE = re.compile(r"^([+-])(\d+(?:\.\d+)?)%$", re.I)
_RATE_RE = re.compile(r"^[+-]\d+%$")
_MAX_ABS_HZ = 220


def pitch_setting_to_communicate_hz(pitch: str) -> str:
    """`EDGE_TTS_PITCH_PCT` → edge-tts 가 허용하는 `+NNHz` (정수만).

    semitone / % 는 대략적 Hz 로 변환. 비어 있거나 형식이 맞지 않으면 `+0Hz`.
    """
    raw = (pitch or "").strip()
    if not raw:
        return "+0Hz"

    m = _HZ_RE.match(raw)
    if m:
        sign, digits = m.groups()
        hz = min(int(digits), _MAX_ABS_HZ)
        return f"{sign}{hz}Hz"

    m = _ST_RE.match(raw)
    if m:
        sign, st = m.groups()
        hz = int(round(float(st) * 30))
        hz = min(max(hz, 0), _MAX_ABS_HZ)
        if hz == 0:
            return "+0Hz"
        return f"{sign}{hz}Hz"

    m = _PCT_RE.match(raw)
    if m:
        sign, pct = m.groups()
        hz = int(round(float(pct) * 4.5))
        hz = min(max(hz, 0), _MAX_ABS_HZ)
        if hz == 0:
            return "+0Hz"
        return f"{sign}{hz}Hz"

    return "+0Hz"


def rate_setting_or_default(rate: str) -> str:
    """`Communicate(..., rate=)` — `^[+-]\\d+%$` 만 허용."""
    r = (rate or "").strip()
    if r and _RATE_RE.match(r):
        return r
    return "+0%"


def _build_communicate(text: str) -> tuple[edge_tts.Communicate, str]:
    """공통 normalize + Communicate 생성. (인스턴스, 정규화된 텍스트) 반환."""
    text = normalize_text_for_korean_piper(text).strip()
    if not text:
        raise ValueError("empty text")
    voice = (settings.edge_tts_voice or "ko-KR-InJoonNeural").strip()
    if not re.fullmatch(r"[\w\-]+", voice):
        raise ValueError(f"invalid edge_tts_voice: {voice!r}")
    pitch_h = pitch_setting_to_communicate_hz(settings.edge_tts_pitch_pct)
    rate_s = rate_setting_or_default(settings.edge_tts_rate)
    return edge_tts.Communicate(text, voice, pitch=pitch_h, rate=rate_s), voice


async def synthesize_edge_mp3_stream(text: str) -> AsyncIterator[bytes]:
    """Yield MP3 chunks as Microsoft 쪽 ``Communicate.stream()`` 에서 도착하는 대로.

    HTTP `StreamingResponse` 의 source 로 그대로 사용. 클라이언트가 첫 chunk 부터
    재생 시작할 수 있어 첫 음성까지의 latency 가 전체 합성을 기다리는 것보다 단축됨.
    """
    communicate, voice = _build_communicate(text)
    total = 0
    async for chunk in communicate.stream():
        if chunk["type"] == "audio" and chunk.get("data"):
            data = chunk["data"]
            total += len(data)
            yield data
    if total < 64:
        # 스트리밍 중에는 raise 해도 클라이언트로 status 전달 불가 — 로그만.
        logging.error("[edge_tts] empty or tiny stream for voice=%s (total=%d)", voice, total)
