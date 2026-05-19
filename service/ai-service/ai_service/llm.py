"""Ollama HTTP 클라이언트 — 의도 분류 + 잡담 응답 호출."""
import json
import logging
import re
from typing import Any

import httpx

from ai_service import prompts
from ai_service.config import settings
from ai_service.emotions import CHAT_EMOTIONS, CHAT_EMOTION_IDS, is_chat_emotion
from ai_service.report_skeleton import (
    build_timeline_skeleton,
    enforce_skeleton_on_events,
    render_skeleton_for_prompt,
)
from ai_service.korean_postprocess import (
    _mode_display_korean,
    robot_display_korean,
    collapse_redundant_class_scope_participation_prefixes,
    dedupe_timeline_near_duplicate_texts,
    ensure_canonical_photo_rows,
    ensure_class_scope_attendance_disclaimer,
    ensure_class_scope_timeline_end_no_data_row,
    fill_timeline_schedule_gaps,
    fix_timeline_child_focus_events,
    merge_attendance_timeline_events,
    merge_final_schedule_slot_timeline_rows,
    normalize_class_scope_dismissal_slots_to_no_data,
    repair_extraneous_class_scope_no_data_rows,
    merge_same_session_photo_clusters_to_single_rows,
    polish_report_json_content,
    retain_top_k_photo_timeline,
    rewrite_photo_event_texts_in_json,
    remove_timeline_raw_emotion_dump_lines,
    rewrite_class_collective_subject_to_child,
    rewrite_class_scope_timeline_child_topic,
    sanitize_photo_event_placements,
    soften_dismissal_no_data_when_intraday_narrative_in_slot,
    strip_lunch_menu_from_non_lunch_events,
    scrub_expression_meta_without_photos,
    scrub_unrecorded_arrival_departure_claims,
    NO_PHOTO_TIMELINE_TEXT_FALLBACK,
    use_class_scope_timeline,
    use_timeline_end_no_data_anchor,
    use_timeline_start_no_data_anchor,
)

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
    from ai_service import prompts

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

    `context` 는 RAG 사실 dict — ai_service.context.build_chat_context() 결과.
    None 이면 빈 컨텍스트로 호출 (테스트 등).

    `{"reply": "...", "emotion": "<chat_eligible id>"}` dict 반환.
    실패 시 LLMError raise. 호출자가 fallback 결정.
    """
    from ai_service.context import format_context_block

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


def _man_age_years_on(birth_date_str: str, report_date_str: str) -> int | None:
    """보고서 기준일의 만 나이 (연·월·일 비교). 파싱 실패 시 None."""
    from datetime import date as Date

    try:
        b = Date.fromisoformat(birth_date_str.strip()[:10])
        o = Date.fromisoformat(report_date_str.strip()[:10])
    except ValueError:
        return None
    years = o.year - b.year
    if (o.month, o.day) < (b.month, b.day):
        years -= 1
    if years < 0:
        return None
    return years


def _schedule_prompt_block(schedule: dict[str, str] | None) -> str:
    if not schedule:
        return (
            "(원 일과표 파일을 불러오지 못했습니다. 등원·간식·점심·낮잠·하원 등 일반 흐름을 참고하세요.)"
        )
    return "\n".join(f"  {slot} — {label}" for slot, label in schedule.items())


async def generate_report(
    *,
    child_name: str,
    date_str: str,
    photo_events: list[dict],
    menu_items: list[str],
    schedule: dict[str, str] | None = None,
    child_notes: str | None = None,
    registered_full_name: str | None = None,
    class_name: str = "",
    birth_date_str: str = "",
    attendance: dict[str, str | None] | None = None,
) -> str:
    """일과 보고서 — 자녀의 하루를 사진(있을 때) + 비사진 활동 타임라인으로 구성.

    Args:
        child_name: 보고서 본문에서 쓸 호칭 (예: "우림")
        date_str: "YYYY-MM-DD"
        photo_events: [{"time": "10:23", "photo_id": 42, "robot": "noriarm",
                        "mode": "ox-quiz", "emotion": "happy", "score": "0.82"}]
                      시각 오름차순. photo_id 는 정수.
        menu_items: 점심메뉴 리스트 (예: ["김밥", "단무지"])
        schedule: `shared/school_schedule.json` 과 동일한 시간대→활동명
        child_notes: DB 교사 특이사항(타임라인·사실 보조 참고; **요약은 오늘 일과 서술 우선**, 특이사항만으로 요약을 짜지 않음)
        registered_full_name: 원 명부 등록명(전체 이름). 호칭과 다를 수 있음 — 프롬프트·후처리에 사용
        class_name, birth_date_str: 프로필 참고
        attendance: ``check_in_kst`` / ``check_out_kst`` (KST HH:MM 또는 None)

    Returns:
        구조화된 JSON 문자열. 형식:
            {"events": [{"time": "HH:MM", "photo_id": int | None, "text": "..."}],
             "summary": "..."}
        events 는 시각 오름차순. 사진 기반 사건은 photo_id 가 입력 값과 동일해야 한다.
        파싱 실패 시 LLMError raise.
    """
    legal = (registered_full_name or "").strip() or child_name.strip()
    call = child_name.strip()
    cls = (class_name or "").strip()
    man_age = _man_age_years_on(birth_date_str, date_str)
    age_hint = (
        f"만 나이(보고서 날짜 기준, 참고): {man_age}세\n" if man_age is not None else ""
    )
    if legal == call:
        identity_block = (
            "원생 이름·반 정보 (DB):\n"
            f"  - 이름(등록명=보고서 호칭): {call}\n"
            f"  - 반 이름(집단·반 전체를 말할 때만 이 문자열을 반 명칭으로 사용): {cls}\n"
            f"  - 이름 뒤에 「반」을 붙여 반 이름을 만들지 마세요 (예: 「{call}반」 금지).\n"
        )
    else:
        identity_block = (
            "원생 이름·반 정보 (DB — 등록명과 보고서 호칭을 혼동하지 마세요):\n"
            f"  - 등록명(원 명부·행정용 전체 이름): {legal}\n"
            f"  - 보고서 호칭(본문에서 이 아이 한 명을 가리킬 때만 사용): {call}\n"
            f"  - 반 이름(집단·반 전체를 말할 때만 이 문자열을 반 명칭으로 사용): {cls}\n"
            f"  - 보고서 호칭 뒤에 「반」을 붙여 반 이름이나 단체를 만들지 마세요 "
            f"(예: 호칭이 「{call}」이어도 「{call}반」은 반 이름이 아님).\n"
            "  - 등록명의 일부(예: 성을 뺀 호칭)를 반 이름·학급명으로 해석하지 마세요.\n"
        )

    has_photos = bool(photo_events)
    photos_block = (
        "\n".join(
            f"- photo_id={p['photo_id']} · {p['time']} (로봇: {robot_display_korean(p['robot'])} / 모드: {_mode_display_korean(p['mode'])}): {p['emotion']} (강도 {p['score']})"
            for p in photo_events
        )
        if has_photos
        else "(없음)"
    )
    menu_block = ", ".join(menu_items) if menu_items else "기록 없음"
    schedule_block = _schedule_prompt_block(schedule)
    notes_stripped = (child_notes or "").strip()
    notes_block = (
        "교사 특이사항 (DB, 참고만 — **타임라인·summary 의 주제로 삼지 말 것**. "
        "낯가림·성격 등 **장기 성향만으로 오늘 하루를 대표하게 쓰지 말 것**):\n"
        f"{notes_stripped}\n\n"
        if notes_stripped
        else ""
    )
    att = attendance or {}
    cin, cout = att.get("check_in_kst"), att.get("check_out_kst")
    att_block = (
        "등하원 (원 DB, KST):\n"
        f"  등원 시각: {cin or '기록 없음'}\n"
        f"  하원 시각: {cout or '기록 없음'}\n\n"
    )
    class_scope_timeline = use_class_scope_timeline(
        att, infer_presence_from_photos=has_photos
    )
    anchor_start = use_timeline_start_no_data_anchor(att, infer_presence_from_photos=has_photos)
    anchor_end = use_timeline_end_no_data_anchor(att)

    # 타임라인 골격은 서버가 정한다 — 일과표 슬롯이 spine 이고, 사진 클러스터·등하원 row 가
    # 슬롯 안에 끼워진다. LLM 은 각 row 의 text 만 채우면 된다.
    skeleton = build_timeline_skeleton(schedule, photo_events, att)
    skeleton_block = render_skeleton_for_prompt(skeleton)

    scope_user_hint = ""
    no_photo_user_hint = ""
    if not has_photos:
        no_photo_user_hint = (
            "\n※ 당일 이 아이에 대한 **로봇 표정 촬영(photo_id)이 한 건도 없습니다**. "
            "events·summary 어디에도 **「오늘 포착된 표정」**, **포착**, **얼굴/표정 촬영**, "
            "**「…의 표정이 기록되었」** 같은 표현을 쓰지 마세요. "
            "일과표·등하원·교사 특이사항에 근거한 활동도 서술합니다.\n"
        )

    if class_scope_timeline:
        cls_hint = (cls or "").strip() or "반"
        scope_user_hint = (
            "\n※ 이 원생의 당일 **등원·하원 시각이 DB 에 비어 있고**, 당일 **로봇 촬영(사진)도 없다**. "
            "일과표 **첫 시각** 줄과 **마지막 구간이 끝나는 시각(예: 18:00)** 줄에만 각각 "
            "**「데이터가 없습니다」 한 문장**을 두고, **그 두 시각이 아닌 줄에는 이 문구를 쓰지 말 것**. "
            "하원·통합 보육이 한 구간(예: 16:00–18:00)이면 **그 구간은 time 을 `16:00-18:00` 처럼 한 줄**로만 두고 "
            "같은 구간을 16:00 과 16:00–18:00 으로 나누어 쓰지 말 것. "
            "중간 시간대는 호칭+「참여 미확인. 「{cls_hint}」 일과로 …」 형식으로 일과표를 풀어 쓸 것. "
            "**「{cls_hint} 아이들은/이」「{cls_hint}반이/는/가」로 문장을 시작하지 말 것**.\n"
        )

    anchor_hint = ""
    if anchor_start:
        anchor_hint += (
            "\n※ **등원**을 DB·당일 사진으로 확인할 수 없으면, 일과표 **첫 시각** 줄에만 "
            "「데이터가 없습니다」 한 문장을 두고 다른 줄에는 이 문구를 쓰지 말 것.\n"
        )
    if anchor_end:
        anchor_hint += (
            "\n※ **하원 시각(check_out_kst)** 이 DB 에 없으면, 일과표 **마지막이 끝나는 시각(예: 18:00)** 줄에만 "
            "「데이터가 없습니다」 한 문장을 두고, 그 줄에 「하원했다」「하원했습니다」 등 실제 하원을 단정하는 표현은 쓰지 말 것. "
            "그 외 시간 줄에는 이 문구를 쓰지 말 것.\n"
        )

    system = (
        "당신은 유치원 교사의 일일 보고서를 한국어로 작성하는 도우미입니다.\n"
        "**중요 — 타임라인 골격은 사용자 메시지에 이미 정해져 있다**:\n"
        "  · events 의 row 개수·순서·각 row 의 `time`·`photo_id` 는 입력 골격과 1:1 로 같아야 한다.\n"
        "  · row 를 추가하거나 삭제하지 말고, 시각을 재배치하지 말 것.\n"
        "  · 각 row 의 `text` 필드만 작성한다. role 표시([schedule], [photo-cluster], "
        "[attendance-in/out], [no-data-start/end], [schedule-end])는 출력에 넣지 말고, 의미만 참고.\n"
        "  · role 이 [no-data-start] 또는 [no-data-end] 인 row 는 정확히 「데이터가 없습니다」 한 문장만 두라.\n"
        "보고서는 시간순 타임라인 형식의 JSON 으로 출력합니다. 각 항목은 events 배열의 한 원소이며,\n"
        "필드는 time (HH:MM), photo_id (정수 또는 null), text (보호자가 읽기 풍부한 한국어 1–2 문장, 대략 70–150 자) 입니다.\n"
        "**짧은 한 줄 금지** — 「오전 간식을 먹었습니다」「교실 활동을 했습니다」처럼 활동명만 붙인 5–15자 한 줄은 보호자가 읽기엔 너무 빈약합니다. "
        "그 시간대에 호칭이 어떻게 보냈는지 (구체 행동·분위기·친구들과의 상호작용·먹은 메뉴·놀이 종류 등) 두 어 절씩 풀어 1–2 문장으로 쓰세요. "
        "단, role 이 [no-data-start]/[no-data-end] 인 줄과 [attendance-in]/[attendance-out] 인 줄은 짧고 정형화된 문장으로 두며 (서버가 강제로 교체합니다).\n"
        "**로봇 이름 음역 금지** — 입력에 영문 id 가 보여도 (예: noriarm, eduping, gogoping) 본문에는 한국어 표기 (노리암 / 에듀핑 / 고고핑) 만 사용. "
        "「노리아르마」「에듀핑이」 같은 음역·합성 표기 금지. 모드 이름도 ox-quiz → 「OX 퀴즈」 처럼 한국어로 쓰세요.\n"
        "예시 — 길이·풍부함 기준 (자연스러운 한국어로):\n"
        "  · 좋음 (약 90자): 「정우는 친구들과 함께 교실에 둘러앉아 색종이로 모양을 만들고, 바깥으로 나가 놀이 기구를 타며 즐겁게 시간을 보냈습니다.」\n"
        "  · 나쁨 (너무 짧음): 「교실 활동을 했습니다」, 「오전 간식을 먹었습니다」.\n"
        "규칙:\n"
        "1) '오늘 포착된 표정' 입력의 각 항목 (photo_id 있음) 은 events 에 반드시 한 번씩 포함하고, "
        "photo_id 는 입력과 동일한 정수, **time 은 입력 촬영 시각과 정확히 같은 HH:MM 한 줄**에만 둡니다. "
        "일과표의 다른 시각 줄(점심·낮잠·오후 등)에는 그 photo_id 를 넣지 말고 photo_id=null 로 두고 해당 시간 활동만 적습니다. "
        "로봇/모드(예: ox-quiz) 언급은 촬영 시각과 같은 그 한 줄에서만 합니다. "
        "text 는 감정·모드 사실에 근거해 자연스럽게 묘사하세요. 감정·시각·모드에 없는 사실은 만들지 마세요. "
        "**한국어 본문에 영문 감정 id·`(강도 숫자)` 입력 형식을 그대로 붙여 한 줄을 쓰지 마세요** "
        "(금지 예: 「happy (강도 1.00)의 표정을 지었습니다」— 보호자용 문장이 아님). "
        "photo_id=null 인 줄에는 **'오늘 포착된 표정'** 이라는 문구나 이와 비슷한 사진 메타 반복을 쓰지 마세요(목차 제목일 뿐이며 점심·낮잠 등 다른 일과와 연결하면 부자연스럽습니다). "
        "같은 문장을 수 분 간격으로 두 번 넣지 마세요(사진이 있는 시각과 거의 같은 말의 비사진 줄 중복 금지).\n"
        "2) photo_id=null 인 각 줄은 **보고서 호칭**을 그 시각 이야기의 주인공으로 반드시 쓴다. "
        "문장·절의 **첫 주어**는 항상 「보고서 호칭+조사」여야 한다. "
        "**「반 이름+아이들은/이/을/를」으로 문장이나 절을 시작하지 말 것** "
        "(틀림: 「햇님반 아이들은 …」, 「햇님반 아이들이 …」 / 좋음: 「정우는 …」, 「민성이 …」). "
        "**반 이름만 단독 주어로 쓰지 말 것**(금지: 「햇님반이 …」「햇님반은 …」 / "
        "좋음: 「민성은 …」「정우는 …」). "
        "반 집단을 쓸 때는 문장 **뒤쪽**에만 짧게 넣는다(예: 호칭이 「햇님반」 친구들과 …). "
        "문장에 '반 이름' 네 글자를 그대로 출력하지 마세요(시스템 설명을 복사하지 않음). "
        "반 친구들과 함께한 모습은 「보고서 호칭」이 주어·화자가 되게 쓰고, 반 전체는 필요할 때만 짧게 보조한다. "
        "반 친구들을 가리킬 때는 DB 「반 이름」**전체** 뒤에 공백을 넣고 「아이들」을 붙인다 "
        "(올바름: 「햇님반 아이들」, 「별반 아이들」 / 금지: 「햇님이들」「별이들」처럼 「반」을 빼고 붙이기). "
        "사진이 없는 시각도 그 시간대 일과를 photo_id=null 한 row 로 **풍부하게** 서술합니다 (한 row 당 1–2 문장, 약 70–150자). "
        "각 줄은 활동명만 괄호로 붙인 한 마디(예: 「…」활동을 했다)가 아니라, 그 시간대에 무엇을 어떻게 했는지 구체적으로(식사·놀이·쉼·친구들과의 상호작용·메뉴·분위기 등) 서술합니다. "
        "일과표에 없는 활동·시간을 새로 만들지 마세요. "
        "**입력된 점심메뉴 목록은 일과표에서 점심에 해당하는 time 한 줄에만** 괄호로 짧게 넣고, "
        "오전 간식·오후 간식 등 **다른 식사 줄에는 점심 메뉴를 복사·붙여넣기 하지 마세요** "
        "(간식 메뉴는 DB 에 없으면 메뉴 괄호를 생략).\n"
        "   · 등원 시각(check_in_kst)이 DB 에 있으면 그 **시각(HH:MM)** 에 "
        "photo_id=null 인 줄로 등원 사실을 밝힌다. **등원 시각이 기록 없음이면** "
        "「등원했다」「등원해」「등원하며」 등 **이 아이의 등원을 단정하는 표현을 쓰지 말 것** "
        "(단, **당일 이 아이의 로봇 촬영(photo_id)이 입력으로 주어지면** 원에 나온 것으로 보고 "
        "등원·아침 일과를 자연스럽게 서술해도 된다). "
        "반 일과·일과표는 서술할 수 있음. "
        "하원 시각(check_out_kst)이 있으면 그 시각에 하원 사실을 밝힌다. "
        "**하원 시각이 없어도** 일과표의 **마지막 시간대까지** photo_id=null 줄을 빠짐없이 두어 "
        "하루 흐름이 비지 않게 한다. 다만 **하원했다** 등 실제 하원을 단정하는 말은 하원 시각이 있을 때만 쓴다.\n"
        "3) events 는 time 오름차순으로 정렬합니다.\n"
        "4) summary 필드는 **보호자가 하루를 한눈에 알 수 있게** 넉넉히 씁니다. "
        "**한 문장만 두고 끝내지 말고**, **2~3문장**(또는 **한글 기준 대략 160~280자**에 가깝게 이어지는 **한 문단**)으로 "
        "오늘의 흐름을 풀어 씁니다. "
        "반드시 **네 가지 이상**의 뼈대(예: 등원·오전(간식/놀이)·점심·낮잠·오후(간식/활동)·로봇·촬영이 있으면 그 구간·마무리)를 "
        "골고루 녹여 **짧은 한 줄 요약**(예: 식사+낮잠만 언급하고 끝내기)은 피합니다. "
        "타임라인의 **서로 다른 시간대**를 **최소 넷 이상** 거친 듯이 읽히게 씁니다. "
        "**summary 는 위 `events` 타임라인에 이미 서술된 오늘 활동·등하원·사진 사실을 한데 묶는 문장**이어야 합니다 "
        "(점심·낮잠·놀이·촬영 구간 등 **오늘 일과 안에서 드러난 흐름**이 중심). "
        "교사 특이사항(`child_notes`)은 **요약의 뼈대나 첫머리로 쓰지 말고**, "
        "오늘 서술과 **맞닿을 때만** 아주 짧게(한 절·수 어절 이하) 덧붙일 수 있습니다. "
        "**특이사항만 앞세우고 오늘 활동을 생략하는 문장**(예: 성향·낯가림만으로 하루를 대표)은 금지입니다. "
        "특이사항이 없거나 오늘 활동과 연결되지 않으면 **요약에서 생략**합니다. "
        "로봇 게임 한 가지만으로 요약을 끝내지 말고 등원·일과·식사·쉼 등 **하루 전체**가 드러나게 합니다. "
        "아이 한 명을 말할 때는 사용자가 준 「보고서 호칭」을 쓰고, 반·학급은 「반 이름(DB)」"
        f"(예: 「{cls}」) 또는 '친구들'로만 짧게 보조한다(타임라인 본문 규칙 2와 같게). "
        "summary 도 **보고서 호칭으로 시작**하고, 「반 이름+아이들은/이」로 시작하지 않는다.\n"
        "   · 주어로 아이를 쓸 때는 「호칭+이/가」형을 쓰고, 「호칭과 다른 아이들」처럼 "
        "「과」로 주어를 잇지 마세요 (올바름: 「호칭이 다른 아이들과」).\n"
        "   · 시간이 '지나다'·'지난 뒤'에 이어질 때는 「점심시간이 지나」「낮잠 시간이 지난」처럼 "
        "시간 명사에는 이/가를 쓰고, 주제 조사 은/는를 쓰지 마세요.\n"
        "5) 인사말·서명·이모지 없음.\n"
        "6) 본문은 표준 한글(한글 음절)만 사용합니다. 한자·중국어·일본어 글자는 쓰지 마세요.\n"
        "7) 이 보고서의 주인공은 한 명뿐입니다. 사용자 메시지의 등록명·보고서 호칭·반 이름을 "
        "서로 바꿔 쓰거나 합성하지 마세요 (호칭+「반」으로 새 반 이름을 만들지 않음).\n"
        "8) 교사 특이사항·등하원·사진 메타는 **타임라인·사실 확인**에만 쓰고, 없는 내용은 지어내지 않습니다. "
        "**특이사항을 요약 문장의 중심으로 두지 마세요** (요약은 오늘 `events` 흐름 우선).\n"
        "9) **보호자(학부모)가 읽는 문서**이므로 events 의 각 text 와 summary 는 **존댓말(합쇼체)**로 통일합니다. "
        "서술·과거 경험은 **…습니다 / …였습니다 / …했습니다 / …었습니다 / …았습니다**, "
        "상태·판단·정체는 **…입니다 / …였습니다** 형태로 끝내고, **반말체로 문장을 끝내지 마세요** "
        "(금지 예: 「…했다」「…였다」「…한다」「…다」로만 끝나는 한 줄). "
        "단, 시스템 안내로 **「데이터가 없습니다」** 한 줄은 그대로 두세요.\n"
        "출력은 반드시 다음 한 줄 JSON 형식만 포함합니다:\n"
        '{"events": [{"time": "HH:MM", "photo_id": int_or_null, "text": "..."}], "summary": "..."}'
    )
    user = (
        identity_block
        + age_hint
        + f"생년월일(DB): {birth_date_str}\n"
        f"보고서 날짜: {date_str}\n"
        f"{att_block}"
        f"{notes_block}"
        f"점심메뉴: {menu_block}\n"
        "원 일과표 (시간대 — 활동명, 참고용):\n"
        f"{schedule_block}\n"
        "오늘 포착된 표정 (photo_id · 시각 · 로봇/모드 · 감정 · 강도, 참고용):\n"
        f"{photos_block}\n\n"
        "**타임라인 골격 (events 의 각 row 와 1:1 대응 — time/photo_id 그대로 유지하고 text 만 작성)**:\n"
        f"{skeleton_block}\n"
        f"{no_photo_user_hint}"
        f"{scope_user_hint}"
        f"{anchor_hint}\n"
        "작성 지침:\n"
        "- events 는 **원 일과표의 모든 시간대**를 빠짐없이 담아 하루가 **일과표 시작부터 끝까지** 이어지게 씁니다. "
        "등원·하원 DB 가 비어 있어도 중간 시간대는 채우되, **미등원이면 등원 사실을 쓰지 말고**, "
        "**미하원이면 하원 사실을 단정하지 말 것**. "
        "위 「등·하원·사진 모두 없음」 안내가 붙은 경우, **하원·통합 보육 시간 줄은 「데이터가 없습니다」만** 두는 것이 맞고, "
        "그 줄에 「하원하며」「통합 보육을 했다」 등을 쓰지 마세요.\n"
        "- 로봇·게임(OX 퀴즈 등)은 **오늘 포착된 표정**에 해당하는 시각·photo_id 줄에서만 자세히 다루고, 다른 줄에는 게임 이름을 반복하지 마세요.\n"
        "- **점심메뉴 괄호**는 점심 시간대 한 줄에만 쓰고, 간식 줄에 같은 메뉴를 다시 쓰지 마세요.\n"
        "- summary 는 **위 events 에 적은 오늘 사실**을 **2~3문장 또는 160~280자 내외의 한 문단**으로 풍부하게 묶습니다. "
        "**한 문장으로 짧게 끊지 말고**, 등원·오전·점심·낮잠·오후·(로봇/촬영)·저녁 루틴 등이 **골고루** 드러나게 씁니다. "
        "교사 특이사항은 **요약의 주제로 삼지 말고**, 오늘 서술과 겹칠 때만 수 어절 이하로 덧붙입니다(아니면 생략).\n"
        "- **존댓말**: 모든 events text·summary 문장은 **합니다/입니다 체**로 끝내 보호자에게 정중한 톤을 유지합니다.\n\n"
        "위 DB·일과표·사진 사실을 바탕으로 events + summary JSON 을 작성해 주세요."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw = await _ollama_chat(
        messages=messages,
        num_predict=2048,
        num_ctx=4096,
        temperature=0.4,
        model=settings.ollama_report_model,
        timeout_s=settings.ollama_report_timeout_s,
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
    # 골격에 맞춰 즉시 재정렬·검증 — LLM 이 row 를 추가/삭제하거나 시각을 바꿔도 여기서 흡수.
    cleaned_events = enforce_skeleton_on_events(
        skeleton,
        cleaned_events,
        address_name=call,
        has_attendance=bool(att.get("check_in_kst") or att.get("check_out_kst")),
    )
    cleaned_events = sanitize_photo_event_placements(cleaned_events, photo_events)
    # ensure_canonical_photo_rows, merge_same_session_photo_clusters_to_single_rows,
    # retain_top_k_photo_timeline, merge_attendance_timeline_events 는 build_timeline_skeleton
    # 이 이미 처리한다 — 다시 호출하면 LLM 의 풍부한 본문을 짧은 formulaic 문구로 덮어쓰거나
    # 서버가 만든 등하원 문장을 덮어써서 결과가 빈약해진다.
    # → 모두 skip. 텍스트 품질 후처리만 이어서 실행한다.
    cleaned_events = dedupe_timeline_near_duplicate_texts(cleaned_events)
    cleaned_events = fill_timeline_schedule_gaps(
        cleaned_events,
        schedule,
        call,
        menu_items,
        attendance,
        infer_presence_from_photos=has_photos,
        class_scope=class_scope_timeline,
        class_name=cls,
    )
    cleaned_events = fix_timeline_child_focus_events(
        cleaned_events,
        call,
        cls,
        schedule,
        attendance,
        infer_presence_from_photos=has_photos,
        class_scope=class_scope_timeline,
    )
    cleaned_events = ensure_class_scope_attendance_disclaimer(
        cleaned_events,
        schedule,
        call,
        cls,
        attendance=att,
        infer_presence_from_photos=has_photos,
    )
    cleaned_events = scrub_unrecorded_arrival_departure_claims(
        cleaned_events,
        call,
        attendance,
        schedule,
        infer_presence_from_photos=has_photos,
        class_scope=class_scope_timeline,
        class_name=cls,
    )
    cleaned_events = rewrite_class_scope_timeline_child_topic(
        cleaned_events,
        call,
        cls,
        class_scope=class_scope_timeline,
    )
    cleaned_events = collapse_redundant_class_scope_participation_prefixes(
        cleaned_events,
        call,
        cls,
        class_scope=class_scope_timeline,
    )
    cleaned_events = normalize_class_scope_dismissal_slots_to_no_data(
        cleaned_events,
        schedule,
        apply_end_slot_no_data=anchor_end,
    )
    cleaned_events = repair_extraneous_class_scope_no_data_rows(
        cleaned_events,
        schedule,
        call,
        cls,
        menu_items,
        attendance,
        infer_presence_from_photos=has_photos,
        narrative_class_scope=class_scope_timeline,
    )
    cleaned_events = strip_lunch_menu_from_non_lunch_events(
        cleaned_events,
        schedule,
        menu_items,
    )
    # 점심 괄호 제거 등 이후에도 LLM 이 넣은 중복 「데이터가 없습니다」가 남지 않게 한 번 더 정리.
    cleaned_events = normalize_class_scope_dismissal_slots_to_no_data(
        cleaned_events,
        schedule,
        apply_end_slot_no_data=anchor_end,
    )
    cleaned_events = repair_extraneous_class_scope_no_data_rows(
        cleaned_events,
        schedule,
        call,
        cls,
        menu_items,
        attendance,
        infer_presence_from_photos=has_photos,
        narrative_class_scope=class_scope_timeline,
    )

    cleaned_events = soften_dismissal_no_data_when_intraday_narrative_in_slot(
        cleaned_events,
        schedule,
        attendance,
        call,
        cls,
        menu_items,
        infer_presence_from_photos=has_photos,
        narrative_class_scope=class_scope_timeline,
    )
    cleaned_events = merge_final_schedule_slot_timeline_rows(cleaned_events, schedule)
    cleaned_events = ensure_class_scope_timeline_end_no_data_row(
        cleaned_events,
        schedule,
        attendance,
    )
    cleaned_events = remove_timeline_raw_emotion_dump_lines(cleaned_events)
    # 최종 anchor — 텍스트 후처리 단계에서 row 가 추가/삭제됐다면 골격으로 다시 정렬.
    cleaned_events = enforce_skeleton_on_events(
        skeleton,
        cleaned_events,
        address_name=call,
        has_attendance=bool(att.get("check_in_kst") or att.get("check_out_kst")),
    )

    if not has_photos:
        for ev in cleaned_events:
            raw_t = str(ev.get("text", ""))
            t = scrub_expression_meta_without_photos(raw_t)
            t = re.sub(r"\s{2,}", " ", t).strip().strip(" ,.;")
            if len(t) < 3:
                ev["text"] = NO_PHOTO_TIMELINE_TEXT_FALLBACK
            else:
                ev["text"] = t

    summary = str(data.get("summary", "")).strip()
    summary = rewrite_class_collective_subject_to_child(
        summary, call, cls, class_scope=class_scope_timeline
    )
    if not has_photos:
        summary = scrub_expression_meta_without_photos(summary)
        summary = re.sub(r"\s{2,}", " ", summary).strip().strip(" ,.;")
        if len(summary) < 3:
            summary = NO_PHOTO_TIMELINE_TEXT_FALLBACK

    raw_json = json.dumps({"events": cleaned_events, "summary": summary}, ensure_ascii=False)
    polished = polish_report_json_content(
        raw_json,
        child_name,
        (registered_full_name or "").strip() or None,
        class_name=cls,
    )
    # 사진이 붙은 row 의 text 를 게임·감정으로 결정론적 재작성. polish 의 이름 fuzzy-fix
    # 가 본문을 또 건드리지 않도록 마지막에 박는다 (LLM 이 사진 시각을 일과표 슬롯으로
    # 끌어 「낮잠으로 피로를 풀었습니다」 같이 사진과 무관한 문장을 만드는 사고 방지).
    polished = rewrite_photo_event_texts_in_json(polished, photo_events, call)
    if not settings.ollama_report_validate_enabled:
        return polished
    try:
        validated = await _validate_polished_daily_report_json(
            polished,
            address_name=call,
            registered_full_name=(registered_full_name or "").strip() or None,
            class_name=cls,
            valid_photo_ids=valid_photo_ids,
        )
    except LLMError as exc:
        logging.warning("[llm] report validator skipped, using draft: %s", exc)
        return polished
    # validator 도 사진 row 텍스트를 손댈 수 있으니 한 번 더.
    return rewrite_photo_event_texts_in_json(validated, photo_events, call)


def _truthy_pass(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "y")
    if isinstance(val, (int, float)):
        return val == 1
    return False


def _parse_report_validator_payload(raw: str) -> dict[str, Any] | None:
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    for candidate in (s, _strip_markdown_json_fence(s)):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict) and "pass" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    dec = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch != "{":
            continue
        try:
            obj, _end = dec.raw_decode(s, i)
            if isinstance(obj, dict) and "pass" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _merge_report_validator_into_draft(
    draft_obj: dict[str, Any],
    rev: dict[str, Any],
    *,
    valid_photo_ids: set[int],
) -> dict[str, Any]:
    """검수 모델이 준 events/summary 를 초안에 합친다(time·photo_id 키 일치 시 text 만 교체).

    events 가 비었거나 생략되면 타임라인은 초안 그대로 두고 summary 만 교체할 수 있다.
    """
    out = json.loads(json.dumps(draft_obj))
    rev_events = rev.get("events")
    rev_by_key: dict[tuple[str, int | None], str] = {}
    if isinstance(rev_events, list):
        for e in rev_events:
            if not isinstance(e, dict):
                continue
            t = str(e.get("time", "")).strip()
            tx = str(e.get("text", "")).strip()
            if not t or not tx:
                continue
            pid = e.get("photo_id")
            pid_n: int | None = None
            if isinstance(pid, int) and pid in valid_photo_ids:
                pid_n = pid
            rev_by_key[(t, pid_n)] = tx
    if rev_by_key and isinstance(out.get("events"), list):
        for ev in out["events"]:
            if not isinstance(ev, dict):
                continue
            t = str(ev.get("time", "")).strip()
            pid = ev.get("photo_id")
            pid_n: int | None = None
            if isinstance(pid, int) and pid in valid_photo_ids:
                pid_n = pid
            key = (t, pid_n)
            if key in rev_by_key:
                ev["text"] = rev_by_key[key]
    rs = rev.get("summary")
    if isinstance(rs, str) and rs.strip():
        out["summary"] = rs.strip()
    return out


async def _validate_polished_daily_report_json(
    polished: str,
    *,
    address_name: str,
    registered_full_name: str | None,
    class_name: str,
    valid_photo_ids: set[int],
) -> str:
    """두 번째 Qwen 호출로 초안 JSON 을 검수. 통과면 그대로, 아니면 교정 events/summary 를 합쳐 재폴리시."""
    try:
        draft_obj = json.loads(polished)
    except json.JSONDecodeError:
        return polished
    if not isinstance(draft_obj, dict):
        return polished
    call = (address_name or "").strip()
    cls = (class_name or "").strip()
    system = (
        "당신은 유치원 일일 보고서(JSON)를 **검수하는** 편집자입니다. "
        "다른 모델이 작성한 초안이며, 보호자(학부모)가 읽는 최종 문서입니다.\n"
        "역할: 한국어 존댓말(합쇼체), 문법, **영문 감정 id·`(강도 숫자)`·`(happy)` 같은 메타 반복**, "
        "「표정우로」같은 오타, "
        "요약이 **지나치게 짧은 경우**(한글 **약 130자 미만**이거나 등원·오전·점심·낮잠·오후·(촬영/로봇) 중 **세 가지 미만**만 "
        "짚는 수준) 또는 문장이 끊긴 경우를 점검합니다.\n"
        "출력은 **JSON 한 객체뿐**입니다. 형식은 반드시 다음 중 하나입니다.\n"
        '1) 문제 없음: {"pass": true}\n'
        "2) 수정 필요(타임라인 문구까지 손봄): {\"pass\": false, \"summary\": \"…\", \"events\": ["
        '{"time":"HH:MM","photo_id":정수또는null,"text":"…"}, …]}\n'
        "3) 요약만 부족할 때: {\"pass\": false, \"summary\": \"…\"} — **summary 만** 길고 자연스럽게 다시 쓰고, "
        "타임라인은 초안과 동일하게 두려면 **events 는 생략**해도 됩니다.\n"
        "· (2)에서 pass 가 false 이면 **summary 와 events 전체 배열**을 넣을 때는 각 event 의 **time·photo_id 는 초안과 동일**하게 두고 **text 만** 고칩니다.\n"
        "· 초안과 같은 길이·같은 순서의 events 를 유지하는 것이 가장 안전합니다.\n"
        "· 사실(등하원·photo_id·시각)을 바꿔 새 사실을 만들지 마세요."
    )
    user = (
        f"보고서 호칭(본문 주인공): 「{call}」\n"
        f"유효한 photo_id 집합(이 정수만 사진 줄에 허용): "
        f"{sorted(valid_photo_ids) if valid_photo_ids else '[]'}\n\n"
        "=== 초안 JSON ===\n"
        f"{polished}\n"
        "=== 끝 ===\n"
        "위 초안만 검수하고 지시한 JSON 형식으로만 답하세요."
    )
    raw = await _ollama_chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        num_predict=settings.ollama_report_validate_num_predict,
        num_ctx=settings.ollama_report_validate_num_ctx,
        temperature=settings.ollama_report_validate_temperature,
        model=settings.ollama_report_validate_model,
        timeout_s=settings.ollama_report_validate_timeout_s,
        top_p=0.82,
        top_k=32,
    )
    payload = _parse_report_validator_payload(raw)
    if not payload:
        logging.warning("[llm] report validator JSON 파싱 실패, 초안 유지: %s", raw[:160])
        return polished
    if _truthy_pass(payload.get("pass")):
        return polished
    merged = _merge_report_validator_into_draft(draft_obj, payload, valid_photo_ids=valid_photo_ids)
    try:
        merged_s = json.dumps(merged, ensure_ascii=False)
    except (TypeError, ValueError):
        return polished
    return polish_report_json_content(
        merged_s,
        call,
        registered_full_name,
        class_name=cls or None,
    )


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
    models = {
        settings.ollama_model,
        settings.ollama_chat_model,
        settings.ollama_report_model,
        settings.ollama_report_validate_model,
    }
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
