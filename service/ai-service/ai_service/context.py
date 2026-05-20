"""LLM 응답 시 사실 근거로 주입할 컨텍스트 모음 — RAG.

점심 메뉴는 pgvector 기반 의미 검색 (Menu.embedding, bge-m3 1024d).
쿼리에 "오늘/내일/어제" 같은 상대 날짜 토큰이 있으면 day 숫자로 치환한 뒤 임베딩.
"""
import asyncio
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ai_service.capabilities.db_attendance import (
    _NAME_UTTERANCE_EXCLUDE,
    _ATTENDANCE_KEYWORDS,
    _format_time_kst,
    fetch_attendance_rows_kst_today,
)
from ai_service.capabilities.db_report import report_utterance_branch
from ai_service.capabilities.schedule_file import load_school_schedule_dict
from ai_service.embed import EmbedError, embed_text
from ai_service.robots import capabilities_for
from control_db.models import Child, Menu
from control_db.session import async_session_maker

_KO_WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

# 쿼리의 cosine 거리 임계 — pgvector 의 <=> 는 cosine distance (0=동일, 2=정반대).
# bge-m3 한국어 매칭에서 0.55 이하면 메뉴 관련 쿼리로 판단.
# "안녕"/"심심해" 같은 잡담은 0.6+ 가 나와 자동 필터링됨.
_DISTANCE_THRESHOLD = 0.55
_MENU_QUERY_TOKENS = ("점심", "메뉴", "급식", "식단", "밥")

# 한글 성씨 1~2자 + 이름 — 로봇·선생님이 부를 때는 이름(부름명) 위주
_HANGUL_ONLY = re.compile(r"^[가-힣]+$")


def child_call_name(raw: str) -> str:
    """DB `child.name` 을 반에서 부르기 좋은 짧은 이름으로 줄인다 (추측 휴리스틱).

    - 공백으로 나뉘면 마지막 토큰(예: '김 민수' → '민수').
    - 한글 3자: 흔한 '성(1)+이름(2)' 가정 → 뒤 2자.
    - 한글 4자: '복성(2)+이름(2)' 가정 → 뒤 2자.
    - 그 외·외자·불확실하면 원문 유지.
    """
    name = raw.strip()
    if not name:
        return ""
    if " " in name:
        parts = [p for p in name.split() if p]
        if len(parts) >= 2:
            return parts[-1]
        name = parts[0] if parts else ""
    if not name:
        return ""
    if _HANGUL_ONLY.match(name):
        n = len(name)
        if n == 2:
            return name
        if n == 3:
            return name[1:]
        if n == 4:
            return name[2:]
        return name
    return name


async def fetch_registered_children_names(*, limit: int = 200) -> list[str] | None:
    """`child` 테이블의 원본 이름 목록. DB 실패 시 None."""
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                select(Child.name).order_by(Child.class_name, Child.name).limit(limit)
            )
            rows = [str(v).strip() for v in result.scalars().all()]
    except Exception as exc:
        logging.debug("[context] 원아 원본명 DB 조회 실패 (무시): %s", exc)
        return None
    out = [r for r in rows if r]
    return out if out else []


def _should_inject_attendance(user_text: str) -> bool:
    """이름만 말하거나 등하원을 물을 때 오늘 attendance 를 LLM 에 넣는다."""
    raw = user_text.strip()
    if not raw:
        return False
    if any(k in raw for k in _ATTENDANCE_KEYWORDS):
        return True
    compact = raw.replace(" ", "")
    if compact in _NAME_UTTERANCE_EXCLUDE:
        return False
    if "안녕" in raw or "감사" in raw or "고마워" in raw:
        return False
    # "물 줘" 같은 일반 한국어 구문이 이름으로 오탐되지 않도록
    # LLM 컨텍스트 주입은 '등하원 키워드' 또는 명시적 자기소개 문장만 허용.
    if re.search(r"저는\s*.+", raw) or re.search(r"내\s*이름은", raw):
        return True
    return False


async def fetch_attendance_summary_kst_today() -> str | None:
    """KST 기준 오늘 등·하원 요약 한 줄. DB 실패 시 None."""
    kst = ZoneInfo("Asia/Seoul")
    today = datetime.now(kst).date()
    rows = await fetch_attendance_rows_kst_today()
    if rows is None:
        return None

    if not rows:
        return (
            f"오늘({today.month}월{today.day}일) 등하원 기록이 DB 에 아직 없습니다. "
            "이름만 말한 경우 선생님께 확인하라고 안내하세요."
        )

    ins: list[str] = []
    outs: list[str] = []
    for name, typ, t in rows:
        label = child_call_name(name)
        ts = _format_time_kst(t, kst)
        if typ == "IN":
            ins.append(f"{label}({ts} 등원)")
        else:
            outs.append(f"{label}({ts} 하원)")

    return (
        "오늘 등하원 요약 — "
        + ("등원: " + ", ".join(ins) if ins else "등원: 기록 없음")
        + " · "
        + ("하원: " + ", ".join(outs) if outs else "하원: 기록 없음")
        + "."
    )


def _format_now_ko(now: datetime) -> str:
    weekday = _KO_WEEKDAYS[now.weekday()]
    period = "오전" if now.hour < 12 else "오후"
    hour12 = now.hour if now.hour <= 12 else now.hour - 12
    if hour12 == 0:
        hour12 = 12
    return (
        f"{now.year}년 {now.month}월 {now.day}일 {weekday} "
        f"{period} {hour12}시 {now.minute}분"
    )


def _normalize_relative_dates(text: str, now: datetime) -> str:
    """쿼리의 '오늘/내일/어제/그저께' 를 day 숫자로 치환해 임베딩 매칭률을 올린다.

    Menu 인덱스 문서가 "5일 점심 메뉴: ..." 형태이므로 쿼리도 day 숫자가 있어야
    의미 매칭이 잘 잡힌다.
    """
    from ai_service.capabilities.db_menu import parse_menu_query_calendar_day

    today = now.day
    tomorrow = (now + timedelta(days=1)).day
    yesterday = (now - timedelta(days=1)).day
    before_yest = (now - timedelta(days=2)).day
    out = (
        text.replace("오늘", f"{today}일")
        .replace("내일", f"{tomorrow}일")
        .replace("그저께", f"{before_yest}일")
        .replace("엊그제", f"{before_yest}일")
        .replace("어제", f"{yesterday}일")
    )
    if any(token in text for token in _MENU_QUERY_TOKENS):
        d_menu, _ = parse_menu_query_calendar_day(text, now)
        out = f"{out.rstrip()} {d_menu}일"
    return out


def _looks_like_menu_query(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return False
    return any(token in normalized for token in _MENU_QUERY_TOKENS)


async def _vector_search_menu(
    query: str,
    *,
    top_k: int = 1,
    threshold: float = _DISTANCE_THRESHOLD,
) -> list[tuple[int, list[str], float]]:
    """쿼리 임베딩 → pgvector cosine distance 정렬 top-k.

    `threshold` 이하 거리만 반환. 임계 초과면 빈 리스트.
    각 원소: (day, items, distance)
    """
    try:
        qvec = await embed_text(query)
    except EmbedError as exc:
        logging.error(f"[context] menu 검색 실패 (임베딩 에러): {exc}")
        return []

    async with async_session_maker() as session:
        # cosine distance: pgvector 의 `<=>` 연산자
        distance = Menu.embedding.cosine_distance(qvec)
        result = await session.execute(
            select(Menu.day, Menu.items, distance.label("distance"))
            .where(Menu.embedding.is_not(None))
            .order_by(distance)
            .limit(top_k)
        )
        rows = result.all()

    return [(d, items, float(dist)) for d, items, dist in rows if dist <= threshold]


async def build_chat_context(
    user_text: str | None = None,
    robot: str | None = None,
) -> dict[str, str]:
    """chat 호출 시 system 에 끼워 넣을 사실 dict.

    `user_text` 가 있으면 vector 검색을 시도. 거리 임계값 안의 메뉴만 inject.
    `robot` 이 주어지면 해당 로봇의 capability 목록도 inject — "뭐 할 수 있어?" 류 질문에 사용.
    """
    sched = load_school_schedule_dict()
    if sched:
        schedule_str = ", ".join(f"{k}: {v}" for k, v in sched.items())
    else:
        schedule_str = "정보 없음"

    now = datetime.utcnow() + timedelta(hours=9)
    ctx: dict[str, str] = {
        "current_time": _format_now_ko(now),
        "school_schedule": schedule_str,
    }

    async def _menu_hits() -> list[tuple[int, list[str], float]]:
        if not user_text or not _looks_like_menu_query(user_text):
            return []
        normalized = _normalize_relative_dates(user_text, now)
        return await _vector_search_menu(normalized, top_k=1)

    async def _attendance_line() -> str | None:
        if not user_text or not _should_inject_attendance(user_text):
            return None
        return await fetch_attendance_summary_kst_today()

    async def _report_note_for_llm() -> str | None:
        if not user_text:
            return None
        _fast, note = await report_utterance_branch(user_text)
        return note

    hits, att, rep_note = await asyncio.gather(
        _menu_hits(),
        _attendance_line(),
        _report_note_for_llm(),
    )
    if hits:
        day, items, _dist = hits[0]
        ctx["lunch_menu"] = f"{day}일 점심 메뉴 — {', '.join(items)}"

    if robot:
        caps = capabilities_for(robot)
        if caps:
            ctx["capabilities"] = "; ".join(f"{m}({d})" for m, d in caps)

    if att:
        ctx["attendance_today"] = att

    if rep_note:
        ctx["report_db_note"] = rep_note

    return ctx


def format_context_block(ctx: dict[str, str]) -> str:
    """system 프롬프트에 inject 할 한국어 블록.

    LLM 친화적으로 라벨링: 사실은 있는 그대로 답하되, 없는 사실은 모른다고 답하도록 가이드.
    """
    lines = ["[지금 알고 있는 사실 — 질문이 이 사실에 해당하면 정확히 답할 것]"]
    if "current_time" in ctx:
        lines.append(f"- 현재 시각: {ctx['current_time']}")
    if "school_schedule" in ctx:
        lines.append(f"- 일과표(일정): {ctx['school_schedule']}")
        if ctx.get("school_schedule", "").strip() != "정보 없음":
            lines.append(
                "  · 일과표·시간표·오늘 일정 질문이면 **위 일과표 한 줄**을 근거로 시간대별로 짧게 말한다. "
                "모른다고 하거나 다른 내용으로 바꾸면 안 됨."
            )
    if "lunch_menu" in ctx:
        lines.append(f"- 점심 메뉴 (DB `Menu` + vector 검색): {ctx['lunch_menu']}")
    else:
        lines.append(
            "- 점심 메뉴(DB): 모름. 추측·합성 금지. '잘 모르겠어요' 라고 답할 것."
        )
    if "report_db_note" in ctx:
        lines.append(f"- 일일보고·보고서 (DB/규칙 안내 — **일과표·시간표와 다름**): {ctx['report_db_note']}")
        lines.append(
            "  · 위 안내가 '이름을 물어보라'·'겹친다'·'DB 읽기 실패' 류면 그대로 따를 것. "
            "보고서 **본문 인용**이 없으면 내용을 지어내지 말 것."
        )
    if "attendance_today" in ctx:
        lines.append(f"- 오늘 등하원 사실 (DB): {ctx['attendance_today']}")
        lines.append(
            "  · 아이가 이름만 말하거나 등원·하원 여부를 물으면 **위 기록만** 근거로 답한다. "
            "등원 목록에 있으면 반갑게 맞이하고 시각을 말하고, 하원만 기록됐으면 하원만, 둘 다 있으면 짧게 둘 다. "
            "이름이 목록에 없으면 '오늘 그 이름의 등하원 기록이 없어요, 선생님께 확인해 주세요'라고 한다. "
            "기록에 없는 사실을 지어내지 말 것."
        )
        lines.append(
            "  · **금지:** 사용자가 이름만 말했을 때 로봇이 그 아이인 것처럼 "
            "'안녕하세요, OO입니다' 식으로 **자기소개**하지 말 것. "
            "항상 로봇이 원아에게 말하는 말투(OO야, …)로만 답한다."
        )
    if "registered_children" in ctx and ctx["registered_children"].strip():
        lines.append(
            "- 원아 부름명 목록 (반에서 부르는 **이름** 위주; DB 성명에서 자동으로 짧게 줄인 경우 있음 — "
            "**이 목록의 이름만** 언급): "
            f"{ctx['registered_children']}"
        )
        lines.append(
            "  · 아이들에게 말할 때도 위 부름명을 쓴다 (성+풀네임으로 딱딱하게 부르지 않기)."
        )
        lines.append(
            "  · 한국에서는 보통 **이름(부름명)** 만 부른다. 아이가 성 없이 이름만 말해도, "
            "위 목록의 부름명·등하원 DB 성명과 **같은 사람**이면 그 아이로 본다."
        )
        lines.append(
            "  · '누구 있어?' '이름이 뭐야?' 류 질문 → 위 목록만 간단히 말한다. "
            "목록 밖 이름·가상 인물·추측 금지. 목록이 비어 있지 않으면 '모른다'고 하면 안 됨."
        )
        lines.append(
            "  · 특정 아이만 물었을 때 → 목록에 있으면 그 이름으로 답, 없으면 "
            "'그 이름은 오늘 명단에 없어요, 선생님께 확인해 주세요'."
        )
    else:
        lines.append(
            "- 원아 이름·반 명단: **알 수 없음**. 이름을 지어내거나 일반화하지 말 것. "
            "'누구 있어?' → '원아 이름은 선생님 화면에서 확인해 주세요' 처럼 안내."
        )

    if "capabilities" in ctx:
        lines.append(
            f"- 본인이 할 수 있는 기능 목록 (CLOSED LIST — 이 목록 안의 것만 가능. "
            f"이 외 기능은 절대 '할 수 있다' 라고 답하지 말 것): {ctx['capabilities']}"
        )
        lines.append(
            "  · '뭐 할 수 있어?' 류 질문 → 위 목록의 기능명만 골라서 답."
        )
        lines.append(
            "  · 특정 기능 가능 여부 질문 → 목록에 그 기능명이 있으면 '할 수 있어요', "
            "없으면 '그건 못 해요' 라고 답. 비슷해 보여도 목록에 없으면 못 함."
        )
        lines.append(
            "  · '~해줘/~하자/~할래' 같이 어떤 동작을 직접 요청 → 목록에 그 기능이 있으면 "
            "수락하는 답, 없으면 '그 기능은 없어요' 또는 '그건 못 해요' 라고 명확히 거절. "
            "거짓으로 '네 해줄게요' 라고 답하면 절대 안 됨. "
            "예: 목록에 '노래' 가 없는데 '노래 불러줘' 라고 하면 → "
            "'노래는 못 불러요. 대신 OO 은 할 수 있어요' 처럼 거절 + 가능한 기능 안내."
        )
    if "registered_children" in ctx and ctx["registered_children"].strip():
        lines.append(
            "[그 외 사실(날씨·개별 아이의 성향·가정 사정·목록에 없는 이름 등) 은 모름 — "
            "모르는 것은 임의로 만들지 말고 '잘 모르겠어요' 또는 선생님께 확인하라고 답할 것]"
        )
    else:
        lines.append(
            "[그 외 사실(날씨·일정·원아 이름·반 구성 등) 은 모름 — "
            "모르는 이유를 임의로 만들지 말고 '잘 모르겠어요' 형태로 솔직히 답할 것]"
        )
    return "\n".join(lines)
