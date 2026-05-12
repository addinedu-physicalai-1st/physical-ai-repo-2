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


async def generate_report(
    *,
    child_name: str,
    date_str: str,
    photo_events: list[dict],
    menu_items: list[str],
) -> str:
    """일과 보고서 — 자녀의 하루를 사진(있을 때) + 비사진 활동 타임라인으로 구성.

    Args:
        child_name: 자녀 이름 (예: "지수")
        date_str: "YYYY-MM-DD"
        photo_events: [{"time": "10:23", "photo_id": 42, "robot": "noriarm",
                        "mode": "ox-quiz", "emotion": "happy", "score": "0.82"}]
                      시각 오름차순. photo_id 는 정수.
        menu_items: 점심메뉴 리스트 (예: ["김밥", "단무지"])

    Returns:
        구조화된 JSON 문자열. 형식:
            {"events": [{"time": "HH:MM", "photo_id": int | None, "text": "..."}],
             "summary": "..."}
        events 는 시각 오름차순. 사진 기반 사건은 photo_id 가 입력 값과 동일해야 한다.
        파싱 실패 시 LLMError raise.
    """
    has_photos = bool(photo_events)
    photos_block = (
        "\n".join(
            f"- photo_id={p['photo_id']} · {p['time']} ({p['robot']}/{p['mode']}): {p['emotion']} (강도 {p['score']})"
            for p in photo_events
        )
        if has_photos
        else "(없음)"
    )
    menu_block = ", ".join(menu_items) if menu_items else "기록 없음"

    system = (
        "당신은 유치원 교사의 일일 보고서를 한국어로 작성하는 도우미입니다.\n"
        "보고서는 시간순 타임라인 형식의 JSON 으로 출력합니다. 각 항목은 events 배열의 한 원소이며,\n"
        "필드는 time (HH:MM), photo_id (정수 또는 null), text (40자 내외 한 줄 한국어 묘사) 입니다.\n"
        "규칙:\n"
        "1) '오늘 포착된 표정' 입력의 각 항목 (photo_id 있음) 은 events 에 반드시 한 번씩 포함하고, "
        "photo_id 는 입력과 동일한 정수, time 도 입력과 동일하게 둡니다. text 는 감정·모드 사실에 근거해 자연스럽게 묘사하세요. "
        "감정·시각·모드에 없는 사실은 만들지 마세요.\n"
        "2) 사진이 없는 시각 (등원·간식·점심·낮잠·자유놀이·하원 등) 은 일반적인 유치원 일과를 참고해 2~5 항목 정도를 적절히 끼워넣되, "
        "photo_id=null 로 두고 짧고 담담한 한 줄 (감정 단정 금지) 로 적습니다. 점심 시각엔 메뉴를 짧게 언급해 주세요.\n"
        "3) events 는 time 오름차순으로 정렬합니다.\n"
        "4) summary 필드에 하루를 정리하는 한 문장 (40~80자) 을 추가합니다.\n"
        "5) 인사말·서명·이모지 없음.\n"
        "출력은 반드시 다음 한 줄 JSON 형식만 포함합니다:\n"
        '{"events": [{"time": "HH:MM", "photo_id": int_or_null, "text": "..."}], "summary": "..."}'
    )
    user = (
        f"자녀 이름: {child_name}\n"
        f"날짜: {date_str}\n"
        f"점심메뉴: {menu_block}\n"
        f"오늘 포착된 표정 (photo_id · 시각 · 로봇/모드 · 감정 · 강도):\n{photos_block}\n\n"
        "위 사실을 사용해 events + summary JSON 을 작성해 주세요."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw = await _ollama_chat(
        messages=messages,
        num_predict=1024,
        num_ctx=4096,
        temperature=0.4,
        model=settings.ollama_chat_model,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        stripped = _strip_markdown_json_fence(raw)
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise LLMError(f"보고서 JSON 파싱 실패: {raw[:200]}") from exc

    events_in = data.get("events")
    if not isinstance(events_in, list):
        raise LLMError("LLM 응답에 events 배열 없음")
    valid_photo_ids = {int(p["photo_id"]) for p in photo_events if "photo_id" in p}
    cleaned_events: list[dict] = []
    for ev in events_in:
        if not isinstance(ev, dict):
            continue
        time_s = str(ev.get("time", "")).strip()
        text_s = str(ev.get("text", "")).strip()
        if not time_s or not text_s:
            continue
        pid = ev.get("photo_id")
        # LLM 환각으로 알 수 없는 photo_id 가 들어오면 null 로 강제.
        pid_int: int | None = None
        if isinstance(pid, int) and pid in valid_photo_ids:
            pid_int = pid
        cleaned_events.append({"time": time_s, "photo_id": pid_int, "text": text_s})
    cleaned_events.sort(key=lambda e: e["time"])

    summary = str(data.get("summary", "")).strip()
    return json.dumps({"events": cleaned_events, "summary": summary}, ensure_ascii=False)


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
