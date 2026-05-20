"""실 Ollama 호출로 chat 행동 회귀 검증.

핸들러 unit test 가 못 잡는 영역 — 프롬프트가 실제 모델에서 의도대로 동작하는지.
검증 전략: LLM 출력은 비결정적이므로 **negative assertion** (금지된 토큰 부재)
+ **느슨한 positive assertion** (한글 존재, emotion 유효 등) 위주로.

실행: Ollama 가 localhost:11434 에서 동작 중이면 `pytest -m ollama` 로 자동 실행.
`scripts/test.sh` 의 ollama 섹션이 자동으로 포함시킨다.
"""
from __future__ import annotations

import re

import pytest

from ai_service.emotions import CHAT_EMOTION_IDS
from ai_service.llm import generate_chat

pytestmark = [pytest.mark.anyio, pytest.mark.ollama]

_HANGUL_RE = re.compile(r"[가-힣]")
_FIRST_PERSON_RE = re.compile(r"(저는|저도|저의|제가|저를|저에게)")
_TEACHER_DEFLECT_RE = re.compile(r"선생님께")


def _assert_valid_shape(result: dict[str, str], min_len: int = 2) -> None:
    """공통 응답 형태 검증 — 한글 reply, 유효 emotion, 최소 길이.

    min_len 은 shape 만 확인 ('네' 같은 1글자 응답도 통과). 응답 품질
    (충분히 engaging 한지) 은 별도 behavior 테스트가 책임진다.
    """
    assert isinstance(result, dict), f"non-dict result: {result!r}"
    reply = result.get("reply", "")
    emotion = result.get("emotion", "")
    assert isinstance(reply, str) and len(reply) >= min_len, (
        f"reply too short or non-str: {reply!r}"
    )
    assert _HANGUL_RE.search(reply), f"reply lacks Hangul: {reply!r}"
    assert emotion in CHAT_EMOTION_IDS, f"invalid emotion id: {emotion!r}"


def _assert_no_first_person(reply: str) -> None:
    """1인칭 대명사 (저는/제가) 금지 — 자기 호칭 규칙."""
    match = _FIRST_PERSON_RE.search(reply)
    assert not match, f"first-person pronoun present: {match.group()!r} in {reply!r}"


# ── A. 일상 잡담은 선생님 deflection 으로 끊기지 않아야 ────────────────────────


@pytest.mark.parametrize(
    "text,robot",
    [
        ("곰돌이 좋아해", "eduping"),
        ("어제 엄마랑 놀았어", "gogoping"),
        ("꿈에 강아지 봤어", "noriarm"),
        ("치킨 먹고 싶어", "gogoping"),
        ("나 노래 잘 불러", "eduping"),
    ],
)
async def test_daily_chat_does_not_deflect_to_teacher(text: str, robot: str) -> None:
    """감정·취향·일상 화제는 '선생님께' 로 끊으면 안 됨 (일상 잡담 규칙)."""
    result = await generate_chat(text, robot)
    _assert_valid_shape(result)
    reply = result["reply"]
    assert not _TEACHER_DEFLECT_RE.search(reply), (
        f"daily chat should not deflect to teacher: input={text!r}, reply={reply!r}"
    )
    _assert_no_first_person(reply)


# ── B. Wake word + 추가 발화 → HelloHandler 가 못 잡은 자연 대화 ─────────────


@pytest.mark.parametrize(
    "text,robot",
    [
        ("에듀핑 잘 지냈어?", "eduping"),
        ("고고핑아 오늘 뭐 했어?", "gogoping"),
    ],
)
async def test_wake_prefix_conversational(text: str, robot: str) -> None:
    """wake word + 자연 대화는 일상 잡담으로 응답해야 함 (deflect 금지)."""
    result = await generate_chat(text, robot)
    _assert_valid_shape(result)
    reply = result["reply"]
    assert not _TEACHER_DEFLECT_RE.search(reply), (
        f"wake-prefix chat should not deflect: input={text!r}, reply={reply!r}"
    )
    _assert_no_first_person(reply)


# ── C. 자기 호칭 규칙은 robot 무관 ────────────────────────────────────────────


@pytest.mark.parametrize("robot", ["eduping", "gogoping", "noriarm"])
async def test_no_first_person_across_robots(robot: str) -> None:
    """3개 로봇 모두 1인칭 대명사 사용 안 함."""
    result = await generate_chat("너 무슨 색 좋아해?", robot)
    _assert_valid_shape(result)
    _assert_no_first_person(result["reply"])


# ── D. emotion 이 항상 유효한 chat_eligible id ────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "안녕",
        "심심해",
        "오늘 날씨 어때",
        "곰돌이 좋아해",
        "나 속상해",
    ],
)
async def test_emotion_always_valid_chat_id(text: str) -> None:
    """emotion 은 chat_eligible 집합 안에 있어야 (sleep 같은 게 새어나오면 안 됨)."""
    result = await generate_chat(text, "gogoping")
    _assert_valid_shape(result)
