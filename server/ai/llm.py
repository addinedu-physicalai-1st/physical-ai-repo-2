"""Ollama HTTP 클라이언트 — 의도 분류 + 잡담 응답 호출."""
import json
import logging
import re
from typing import Any

import httpx

from server.ai import prompts
from server.ai.config import settings
from server.ai.emotions import CHAT_EMOTIONS, CHAT_EMOTION_IDS, is_chat_emotion

_http_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(timeout=settings.request_timeout_s)
    return _http_client


def _emotions_block() -> str:
    return "\n".join(f"- {e['id']}: {e['description']}" for e in CHAT_EMOTIONS)


def _strip_markdown_json_fence(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _parse_ollama_chat_json(raw: str) -> dict[str, Any] | None:
    """Ollama 가 지문·코드펜스·앞뒤 잡담과 섞어 내도 첫 유효 JSON 객체를 꺼낸다."""
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    for candidate in (s, _strip_markdown_json_fence(s)):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and "reply" in obj:
                return obj
        except json.JSONDecodeError:
            pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch != "{":
            continue
        try:
            obj, _end = dec.raw_decode(s, i)
            if isinstance(obj, dict) and "reply" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _chat_payload_ok(data: dict[str, Any] | None) -> bool:
    if not data or not isinstance(data, dict):
        return False
    return bool(str(data.get("reply", "")).strip())


def _normalize_chat_dict(data: dict[str, Any]) -> dict[str, str]:
    reply = str(data.get("reply", "")).strip()
    emotion = str(data.get("emotion", "basic")).strip()
    if not is_chat_emotion(emotion):
        emotion = "basic"
    return {"reply": reply, "emotion": emotion}


async def _ollama_chat_json_repair(
    *, user_text: str, robot: str, timeout_s: float | None = None
) -> str:
    """긴 chat 프롬프트가 타임아웃이거나 JSON 만 깨졌을 때 — 짧은 시스템으로 한 줄 재요청."""
    from server.ai import prompts

    name = prompts.display_name(robot)
    ids_csv = ",".join(CHAT_EMOTION_IDS)
    system = (
        f"당신은 유치원 로봇 {name}입니다. 아이의 질문에 한두 문장만 한국어로 답합니다. "
        f'반드시 JSON 한 줄만 출력합니다. 형식: {{"reply":"한글만","emotion":"<id>"}} '
        f"emotion 은 다음 중 정확히 하나입니다: {ids_csv}."
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_text},
    ]
    t = (
        timeout_s
        if timeout_s is not None
        else max(2.0, min(3.0, settings.ollama_chat_timeout_s * 0.72))
    )
    return await _ollama_chat(
        messages=messages,
        num_predict=96,
        num_ctx=384,
        temperature=0.36,
        model=settings.ollama_chat_model,
        timeout_s=t,
        top_p=0.86,
        top_k=settings.ollama_chat_top_k,
    )


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
        num_predict=settings.ollama_classify_num_predict,
        num_ctx=settings.ollama_classify_num_ctx,
        temperature=0.1,
    )

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise LLMError(f"JSON 파싱 실패: {raw[:200]}")


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
    if settings.ollama_chat_use_few_shot:
        for user_msg, assistant_obj in prompts.chat_few_shot(robot):
            messages.append({"role": "user", "content": user_msg})
            messages.append(
                {"role": "assistant", "content": json.dumps(assistant_obj, ensure_ascii=False)}
            )
    messages.append({"role": "user", "content": text})

    base_t = settings.ollama_chat_timeout_s
    raw = ""
    last_net_err: LLMError | None = None
    try:
        raw = await _ollama_chat(
            messages=messages,
            num_predict=settings.ollama_chat_num_predict,
            num_ctx=settings.ollama_chat_num_ctx,
            temperature=settings.ollama_chat_temperature,
            model=settings.ollama_chat_model,
            timeout_s=base_t,
            top_p=settings.ollama_chat_top_p,
            top_k=settings.ollama_chat_top_k,
        )
    except LLMError as exc:
        last_net_err = exc
        logging.warning("[llm] chat primary Ollama 실패 (timeout/HTTP 등): %s", exc)
        try:
            raw = await _ollama_chat_json_repair(
                user_text=text,
                robot=robot,
                timeout_s=max(2.5, base_t * 0.9),
            )
        except LLMError as exc2:
            logging.warning("[llm] chat compact repair 실패: %s", exc2)
            raise last_net_err from exc2

    data = _parse_ollama_chat_json(raw)
    if not _chat_payload_ok(data):
        try:
            raw2 = await _ollama_chat_json_repair(
                user_text=text,
                robot=robot,
                timeout_s=max(2.5, base_t * 0.9),
            )
        except LLMError:
            raw2 = ""
        data = _parse_ollama_chat_json(raw2) if raw2 else None

    if not _chat_payload_ok(data):
        # 파싱·재시도 실패 — TTS 가 읽을 수 있는 짧은 한국어 안내
        data = {"reply": "지금 잘 못 들었어요. 한 번만 더 말해줄래요?", "emotion": "basic"}

    return _normalize_chat_dict(data)


async def generate_bento_prompt(items: list[str]) -> str:
    """Ollama 를 사용하여 급식 메뉴 기반의 이미지 생성 프롬프트를 생성."""
    from server.ai.prompts import lunch_image
    
    messages = [
        {"role": "system", "content": lunch_image.bento_prompt_system()},
        {"role": "user", "content": lunch_image.bento_prompt_user(items)},
    ]

    raw = await _ollama_chat(
        messages=messages,
        num_predict=200,
        num_ctx=1024,
        temperature=0.7,
    )
    
    try:
        data = json.loads(raw)
        return data.get("prompt", raw)
    except json.JSONDecodeError:
        return raw


async def _ollama_chat(
    *,
    messages: list[dict[str, str]],
    num_predict: int,
    num_ctx: int,
    temperature: float,
    model: str | None = None,
    timeout_s: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
) -> str:
    read_s = timeout_s if timeout_s is not None else settings.request_timeout_s
    options: dict[str, Any] = {
        "temperature": temperature,
        "num_predict": num_predict,
        "num_ctx": num_ctx,
    }
    if top_p is not None:
        options["top_p"] = top_p
    if top_k is not None and top_k > 0:
        options["top_k"] = top_k
    payload: dict[str, Any] = {
        "model": model or settings.ollama_model,
        "messages": messages,
        "stream": False,
        "keep_alive": settings.ollama_keep_alive,
        "options": options,
    }
    payload["format"] = "json"

    try:
        response = await _get_client().post(
            f"{settings.ollama_host}/api/chat",
            json=payload,
            timeout=httpx.Timeout(read_s, connect=1.2),
        )
        response.raise_for_status()
        result = response.json()
    except httpx.HTTPError as exc:
        raise LLMError(f"Ollama 통신 실패: {exc}") from exc

    raw = (result.get("message", {}).get("content") or "").strip()
    if not raw:
        raise LLMError("Ollama 빈 응답")
    return raw


async def warmup_ollama_models() -> None:
    """Ollama 에 극소 프롬프트를 보내 가중치를 메모리에 올린다. 실패해도 무시."""
    host = settings.ollama_host.rstrip("/")
    ka = settings.ollama_keep_alive
    models = {settings.ollama_model, settings.ollama_chat_model}
    client = _get_client()
    for name in models:
        try:
            r = await client.post(
                f"{host}/api/generate",
                json={
                    "model": name,
                    "prompt": ".",
                    "stream": False,
                    "keep_alive": ka,
                    "options": {"num_predict": 1, "num_ctx": 128, "temperature": 0},
                },
                timeout=min(90.0, settings.request_timeout_s),
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            logging.warning("[llm] Ollama warmup 실패 (%s): %s", name, exc)
