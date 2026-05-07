"""LLM 응답 시 사실 근거로 주입할 컨텍스트 모음 — RAG.

점심 메뉴는 pgvector 기반 의미 검색 (Menu.embedding, bge-m3 1024d).
쿼리에 "오늘/내일/어제" 같은 상대 날짜 토큰이 있으면 day 숫자로 치환한 뒤 임베딩.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from server.ai.embed import EmbedError, embed_text
from server.ai.robots import capabilities_for
from server.db.models import Menu
from server.db.session import async_session_maker

_KO_WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

# 쿼리의 cosine 거리 임계 — pgvector 의 <=> 는 cosine distance (0=동일, 2=정반대).
# bge-m3 한국어 매칭에서 0.55 이하면 메뉴 관련 쿼리로 판단.
# "안녕"/"심심해" 같은 잡담은 0.6+ 가 나와 자동 필터링됨.
_DISTANCE_THRESHOLD = 0.55


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
    """쿼리의 '오늘/내일/어제' 를 day 숫자로 치환해 임베딩 매칭률을 올린다.

    Menu 인덱스 문서가 "5일 점심 메뉴: ..." 형태이므로 쿼리도 day 숫자가 있어야
    의미 매칭이 잘 잡힌다.
    """
    today = now.day
    tomorrow = (now + timedelta(days=1)).day
    yesterday = (now - timedelta(days=1)).day
    return (
        text.replace("오늘", f"{today}일")
        .replace("내일", f"{tomorrow}일")
        .replace("어제", f"{yesterday}일")
    )


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
    # KST (UTC+9) 기준으로 현재 시각 계산
    now = datetime.utcnow() + timedelta(hours=9)
    ctx: dict[str, str] = {
        "current_time": _format_now_ko(now),
        "school_schedule": (
            "09:00-10:00: 등원 및 자유놀이, "
            "10:00-10:30: 오전 간식, "
            "10:30-12:00: 교실 활동 및 바깥 놀이, "
            "12:00-13:00: 점심시간, "
            "13:00-14:30: 낮잠 및 휴식, "
            "14:30-15:00: 오후 간식, "
            "15:00-16:00: 오후 특별 활동, "
            "16:00-18:00: 하원 및 통합 보육"
        )
    }

    if user_text:
        normalized = _normalize_relative_dates(user_text, now)
        hits = await _vector_search_menu(normalized, top_k=1)
        if hits:
            day, items, _dist = hits[0]
            ctx["lunch_menu"] = f"{day}일 점심 메뉴 — {', '.join(items)}"

    if robot:
        caps = capabilities_for(robot)
        if caps:
            ctx["capabilities"] = "; ".join(f"{m}({d})" for m, d in caps)

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
    if "lunch_menu" in ctx:
        lines.append(f"- 점심 메뉴 (vector 검색 결과): {ctx['lunch_menu']}")
    else:
        lines.append(
            "- 점심 메뉴: 모름. 추측·합성 금지. '잘 모르겠어요' 라고 답할 것."
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
    lines.append(
        "[그 외 사실(날씨·일정·아이 이름 등) 은 모름 — "
        "모르는 이유를 임의로 만들지 말고 '잘 모르겠어요' 형태로 솔직히 답할 것]"
    )
    return "\n".join(lines)
