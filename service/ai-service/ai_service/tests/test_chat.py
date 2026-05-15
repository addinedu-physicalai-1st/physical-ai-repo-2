"""generate_chat — JSON 파싱·한국어·감정 id (모킹).

실 모델은 길이·emotion 문자열을 스키마에서 벗어나게 내는 경우가 많다.
회귀 방지용으로 `_ollama_chat` 이 돌려주는 JSON 이 그대로 반영되는지 검증한다.

느슨한 실 Ollama 스모크: `RUN_LLM_SMOKE=1 pytest -m llm_smoke`
"""
import json
import os
import re
from unittest.mock import AsyncMock, patch

import pytest

from ai_service.emotions import CHAT_EMOTION_IDS
from ai_service.llm import LLMError, _parse_ollama_chat_json, generate_chat

pytestmark = pytest.mark.anyio

_HANGUL_RE = re.compile(r"[가-힣]")


@pytest.mark.parametrize(
    "text,robot,payload",
    [
        ("하이", "gogoping", {"reply": "안녕 반가워요!", "emotion": "hello"}),
        ("심심해", "eduping", {"reply": "에듀핑이랑 같이 놀자!", "emotion": "fun"}),
        ("오늘 날씨 어때", "noriarm", {"reply": "노리암은 밖에 못 나가서 잘 몰라요.", "emotion": "basic"}),
        ("엄마 보고싶어", "gogoping", {"reply": "에휴, 보고 싶겠다.", "emotion": "sad"}),
        ("몇 시야", "noriarm", {"reply": "시계는 선생님 화면에 있어요.", "emotion": "interest"}),
    ],
)
async def test_generate_chat_parses_ollama_json(
    text: str, robot: str, payload: dict
) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    with patch("ai_service.llm._ollama_chat", new_callable=AsyncMock, return_value=raw):
        result = await generate_chat(text, robot)
    assert result["reply"] == payload["reply"]
    assert result["emotion"] == payload["emotion"]
    assert _HANGUL_RE.search(result["reply"])
    assert result["emotion"] in CHAT_EMOTION_IDS


@pytest.mark.parametrize("raw", ["not json at all", "{broken json"])
async def test_generate_chat_non_json_falls_back_to_korean_prompt(
    raw: str,
) -> None:
    with patch("ai_service.llm._ollama_chat", new_callable=AsyncMock, return_value=raw):
        result = await generate_chat("anything", "gogoping")
    # 본 호출 + JSON 복구 재호출 모두 실패 시 안내 문구
    assert "한 번만 더" in result["reply"]
    assert _HANGUL_RE.search(result["reply"])
    assert result["emotion"] == "basic"


async def test_generate_chat_repair_call_restores_json() -> None:
    good = json.dumps(
        {"reply": "투자는 돈을 잘 굴리는 방법을 연구하는 거예요.", "emotion": "interest"},
        ensure_ascii=False,
    )
    with patch(
        "ai_service.llm._ollama_chat",
        new_callable=AsyncMock,
        side_effect=["not json {broken", good],
    ):
        result = await generate_chat("워렌 버핏 전략이 뭐야", "gogoping")
    assert "투자" in result["reply"]
    assert result["emotion"] == "interest"


def test_parse_ollama_chat_json_fenced_and_prefix() -> None:
    inner = {"reply": "답", "emotion": "hello"}
    raw = '설명:\n```json\n' + json.dumps(inner, ensure_ascii=False) + "\n```"
    assert _parse_ollama_chat_json(raw) == inner
    prefixed = '알겠습니다. ' + json.dumps(inner, ensure_ascii=False) + " 끝."
    assert _parse_ollama_chat_json(prefixed) == inner


async def test_generate_chat_retries_after_primary_ollama_error() -> None:
    good = json.dumps(
        {"reply": "물은 조금씩 자주 마시면 좋아요.", "emotion": "happy"},
        ensure_ascii=False,
    )
    with patch(
        "ai_service.llm._ollama_chat",
        new_callable=AsyncMock,
        side_effect=[LLMError("timeout"), good],
    ) as m:
        result = await generate_chat("하루에 물 얼마나 마셔야 해", "gogoping")
    assert m.await_count == 2
    assert "물" in result["reply"]
    assert result["emotion"] == "happy"


async def test_generate_chat_raises_when_primary_and_repair_both_fail() -> None:
    with patch(
        "ai_service.llm._ollama_chat",
        new_callable=AsyncMock,
        side_effect=[LLMError("primary"), LLMError("repair")],
    ) as m:
        with pytest.raises(LLMError):
            await generate_chat("테스트", "gogoping")
    assert m.await_count == 2


async def test_generate_chat_invalid_emotion_normalized_to_basic() -> None:
    raw = json.dumps({"reply": "테스트", "emotion": "not_a_chat_emotion"}, ensure_ascii=False)
    with patch("ai_service.llm._ollama_chat", new_callable=AsyncMock, return_value=raw):
        result = await generate_chat("x", "eduping")
    assert result["reply"] == "테스트"
    assert result["emotion"] == "basic"


@pytest.mark.ollama
@pytest.mark.llm_smoke
@pytest.mark.skipif(not os.environ.get("RUN_LLM_SMOKE"), reason="set RUN_LLM_SMOKE=1 to enable")
async def test_chat_real_ollama_smoke() -> None:
    result = await generate_chat("하이", "gogoping")
    assert isinstance(result.get("reply"), str) and len(result["reply"]) > 0
    assert isinstance(result.get("emotion"), str)
