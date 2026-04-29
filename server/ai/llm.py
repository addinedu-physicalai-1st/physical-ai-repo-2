"""Ollama HTTP 클라이언트 — 의도 분류 + 잡담 응답 호출."""
import json
import re
from typing import Any

_KIND_RE = re.compile(r'"kind"\s*:\s*"(\w+)"')
_HANGUL_RE = re.compile(r"[가-힣]")
_REPLY_RE = re.compile(r'"reply"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"')

# 모르는 사실을 합리화하려는 hallucination 패턴 — 잡히면 "모르겠어요" 로 fallback.
# 점심 메뉴 미주입 시에도 "아직 정해지지 않았어요" 같이 답하는 모델 버릇을 잡는다.
_HALLUCINATION_PATTERNS = [
    re.compile(r"아직\s*정해지지\s*않"),
    re.compile(r"아직\s*정해지지\s*않았"),
    re.compile(r"정해지지\s*않았어요"),
]

import httpx

from server.ai import prompts
from server.ai.config import settings
from server.ai.emotions import CHAT_EMOTIONS, CHAT_EMOTION_IDS

_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=settings.request_timeout_s)
    return _http_client


def _emotions_block() -> str:
    return "\n".join(f"- {e['id']}: {e['description']}" for e in CHAT_EMOTIONS)


class LLMError(Exception):
    pass


async def classify_intent(text: str, robot: str) -> dict[str, Any]:
    """Ollama 호출 → 의도 분류 결과 dict 반환.

    실패 시 LLMError raise. 호출자가 fallback 결정.
    """
    system = prompts.classify_system(robot)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": text},
    ]

    raw = await _ollama_chat(
        messages=messages,
        json_format=True,
        num_predict=60,
        num_ctx=2048,
        temperature=0.1,
    )

    try:
        parsed: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        # 모델이 reason 같은 추가 필드를 달아 JSON 이 잘린 경우 kind 만 추출
        m = _KIND_RE.search(raw)
        if not m:
            raise LLMError(f"JSON 파싱 실패: {raw[:200]}")
        kind = m.group(1)
        if kind not in {"mode_change", "sub_command", "ignored"}:
            raise LLMError(f"알 수 없는 kind: {kind}")
        parsed = {"kind": kind}

    return parsed


async def generate_chat(
    text: str,
    robot: str,
    context: dict[str, str] | None = None,
) -> dict[str, str]:
    """모드 전환·정지 어디에도 해당 안 되는 발화에 대한 자연어 대화 응답.

    `context` 는 RAG 사실 dict — server.ai.context.build_chat_context() 결과.
    None 이면 빈 컨텍스트로 호출 (테스트 등).

    `{"reply": "...", "emotion": "<chat_eligible id>"}` dict 반환.
    실패 시 LLMError raise. 호출자가 fallback 결정.
    """
    from server.ai.context import format_context_block

    system = prompts.chat_system(
        robot,
        context_block=format_context_block(context or {}),
        emotions_block=_emotions_block(),
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    for user_msg, assistant_obj in prompts.chat_few_shot(robot):
        messages.append({"role": "user", "content": user_msg})
        messages.append(
            {"role": "assistant", "content": json.dumps(assistant_obj, ensure_ascii=False)}
        )
    messages.append({"role": "user", "content": text})

    raw = await _ollama_chat(
        messages=messages,
        json_format=True,
        num_predict=200,
        num_ctx=3072,
        temperature=0.6,
        model=settings.ollama_chat_model,
    )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # 출력이 잘렸거나 추가 토큰 — reply 만이라도 추출
        m = _REPLY_RE.search(raw)
        if not m:
            raise LLMError(f"chat JSON 파싱 실패: {raw[:200]}")
        parsed = {"reply": m.group(1)}

    reply = (parsed.get("reply") or "").strip()
    if not reply or not _HANGUL_RE.search(reply):
        raise LLMError("한국어 응답 없음")

    emotion = parsed.get("emotion")
    if emotion not in CHAT_EMOTION_IDS:
        # LLM 이 잘못된 id 를 뱉으면 중립 fallback
        emotion = "basic"

    # 모르는 사실을 합리화하는 패턴이 잡히면 안전 응답으로 치환.
    # context 에 없는 메뉴를 "아직 정해지지 않았어요" 식으로 지어내는 것을 방지.
    if any(p.search(reply) for p in _HALLUCINATION_PATTERNS):
        reply = "그건 저도 잘 모르겠어요. 선생님께 여쭤볼까요?"
        emotion = "basic"

    return {"reply": reply, "emotion": emotion}


async def _ollama_chat(
    *,
    messages: list[dict[str, str]],
    json_format: bool,
    num_predict: int,
    num_ctx: int,
    temperature: float,
    model: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "model": model or settings.ollama_model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
            "num_ctx": num_ctx,
        },
    }
    if json_format:
        payload["format"] = "json"

    try:
        response = await _get_client().post(
            f"{settings.ollama_host}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        result = response.json()
    except httpx.HTTPError as exc:
        raise LLMError(f"Ollama 통신 실패: {exc}") from exc

    raw = (result.get("message", {}).get("content") or "").strip()
    if not raw:
        raise LLMError("Ollama 빈 응답")
    return raw
