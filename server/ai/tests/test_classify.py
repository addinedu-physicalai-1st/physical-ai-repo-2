"""classify_intent — Ollama 응답 JSON 파싱·계약 (모킹).

실제 소형 모델(qwen2.5:0.5b 등)은 JSON 스키마를 자주 어겨 통합 테스트가 불안정하다.
Hub `/voice/intent` 는 규칙 기반 + `generate_chat` 이 주 경로이므로, 여기서는 **모킹된 Ollama 한 줄 JSON** 이
`classify_intent` 에 그대로 전달되는지 검증한다.

실 Ollama로 느슨한 스모크를 돌리려면: `RUN_LLM_SMOKE=1 pytest -m llm_smoke`
"""
import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from server.ai.llm import classify_intent

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "robot,payload",
    [
        ("gogoping", {"kind": "mode_change", "mode": "자장가"}),
        ("gogoping", {"kind": "sub_command", "action": "stop"}),
        ("gogoping", {"kind": "ignored"}),
        ("eduping", {"kind": "mode_change", "mode": "율동"}),
        ("noriarm", {"kind": "mode_change", "mode": "블럭쌓기"}),
    ],
)
async def test_classify_intent_returns_parsed_json(robot: str, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    with patch("server.ai.llm._ollama_chat", new_callable=AsyncMock, return_value=raw):
        result = await classify_intent("dummy", robot)
    assert result == payload


@pytest.mark.ollama
@pytest.mark.llm_smoke
@pytest.mark.skipif(not os.environ.get("RUN_LLM_SMOKE"), reason="set RUN_LLM_SMOKE=1 to enable")
async def test_classify_real_ollama_returns_dict() -> None:
    """프롬프트 준수 여부는 모델에 따라 다름 — 형태만 확인."""
    result = await classify_intent("안녕", "gogoping")
    assert isinstance(result, dict)
    assert "kind" in result
