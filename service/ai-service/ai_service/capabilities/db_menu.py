"""점심 메뉴 빠른 조회 — Menu 테이블 직접 lookup + 한국어 상대 날짜 파싱.

기존 `ai_service.context` 에서 이전. 시그니처·동작은 그대로 유지.

- `parse_menu_query_calendar_day`: 자연어 → (day_of_month, relative_token)
- `get_menu_fast`: day → 구어체 TTS 문장
"""
import re
from datetime import datetime, timedelta

from sqlalchemy import select

from control_db.models import Menu
from control_db.session import async_session_maker


# 하루=1일 간격 … 닷새=5일 (전통 표현). 허브 메뉴 빠른 경로·임베딩 정규화에서 공통 사용.
_KO_DAY_SPAN_WORDS: tuple[tuple[str, int], ...] = (
    ("닷새", 5),
    ("나흘", 4),
    ("사흘", 3),
    ("이틀", 2),
    ("하루", 1),
)
_KO_FUTURE_AFTER = re.compile(
    r"(하루|이틀|사흘|나흘|닷새)\s*(뒤|뒤에|후|만에|있다가|이따가)",
    re.UNICODE,
)
_KO_PAST_BEFORE = re.compile(
    r"(하루|이틀|사흘|나흘|닷새)\s*(전|전에|이전)",
    re.UNICODE,
)


def parse_menu_query_calendar_day(text: str, now: datetime) -> tuple[int, str | None]:
    """메뉴 질문에서 `Menu.day`(월 중 일)와 `get_menu_fast(..., relative=)` 를 추출.

    월말·월초 경계는 DB 가 `day` 만 저장하는 한계로 어긋날 수 있음(기존과 동일).
    """
    t = text.strip()
    c = re.sub(r"\s+", "", t)

    def _offset_day(delta: int) -> int:
        return (now.date() + timedelta(days=delta)).day

    if "내일모레" in c or ("내일" in t and "모레" in t):
        return _offset_day(2), None
    if "그저께" in t or "엊그제" in t:
        return _offset_day(-2), "day_before_yesterday"
    if "그끄저께" in t:
        return _offset_day(-3), None
    if "어제" in t:
        return _offset_day(-1), "yesterday"
    if "내일" in t and "모레" not in t:
        return _offset_day(1), None
    if "모레" in t:
        return _offset_day(2), None
    if "글피" in t:
        return _offset_day(3), None
    if "오늘" in t:
        return now.day, None

    m_past = _KO_PAST_BEFORE.search(t)
    if m_past:
        span = m_past.group(1)
        n = dict(_KO_DAY_SPAN_WORDS).get(span, 1)
        return _offset_day(-n), None

    m_fut = _KO_FUTURE_AFTER.search(t)
    if m_fut:
        span = m_fut.group(1)
        n = dict(_KO_DAY_SPAN_WORDS).get(span, 1)
        return _offset_day(n), None

    m_num_fut = re.search(r"(\d+)\s*일\s*(뒤|뒤에|후|만에|있다가)", t)
    if m_num_fut:
        return _offset_day(int(m_num_fut.group(1))), None

    m_num_past = re.search(r"(\d+)\s*일\s*(전|전에|이전)", t)
    if m_num_past:
        return _offset_day(-int(m_num_past.group(1))), None

    m_dom = re.search(r"(?<!\d)(\d{1,2})\s*일(?!\s*(뒤|뒤에|후|만에|전|전에|이전))", t)
    if m_dom:
        dom = int(m_dom.group(1))
        if 1 <= dom <= 31:
            return dom, None

    return now.day, None


def _ida_polite_copula_after(last_noun: str) -> tuple[str, str]:
    """마지막 명사에 붙는 평서형 서술어 (이다 준말): (현재 ~해요체, 과거).

    받침 있음 → 이에요 / 이었어요 — 예: 귤이에요, 쌀밥이에요
    받침 없음 → 예요 / 였어요 — 예: 바나나예요, 김치찌개예요 (띄어 쓰기 ``바나나 이예요`` 금지)
    """
    s = (last_noun or "").strip()
    if not s:
        return "이에요", "이었어요"
    ch = s[-1]
    o = ord(ch)
    if 0xAC00 <= o <= 0xD7A3:
        has_batchim = (o - 0xAC00) % 28 != 0
        if has_batchim:
            return "이에요", "이었어요"
        return "예요", "였어요"
    return "이에요", "이었어요"


async def get_menu_fast(
    day: int,
    *,
    relative: str | None = None,
) -> str:
    """지정된 날짜의 메뉴를 DB 에서 직접 조회.

    `relative` 가 있으면 사용자가 말한 상대 시각(어제/그저께)에 맞춰 문장을 고정한다.
    (DB 는 월 내 `day` 만 저장하므로, 월 경계는 한계가 있음.)
    """
    async with async_session_maker() as session:
        result = await session.execute(select(Menu).where(Menu.day == day))
        m = result.scalar_one_or_none()
        if m:
            now = datetime.utcnow() + timedelta(hours=9)

            if relative == "yesterday":
                date_str = "어제"
                suffix = "맛있게 드셨나요?"
            elif relative == "day_before_yesterday":
                date_str = "그저께"
                suffix = "맛있게 드셨나요?"
            elif day == now.day:
                date_str = "오늘"
                suffix = "맛있게 먹어요!"
            elif day == (now + timedelta(days=1)).day:
                date_str = "내일"
                suffix = "맛있게 먹어요!"
            elif day == (now + timedelta(days=2)).day:
                date_str = "내일 모레"
                suffix = "맛있게 먹어요!"
            elif day == (now + timedelta(days=3)).day:
                date_str = "글피"
                suffix = "맛있게 먹어요!"
            elif day < now.day:
                date_str = f"{day}일"
                suffix = "맛있게 드셨나요?"
            else:
                date_str = f"{day}일"
                suffix = "맛있게 먹어요!"

            # TTS·구어체: 나열 뒤 서술어는 **마지막 항**에만 붙인다. 받침 유무로 이에요/예요 구분.
            items_list = [x.strip() for x in m.items if str(x).strip()]
            if not items_list:
                return f"{day}일 점심 메뉴 정보가 없어요."
            if len(items_list) == 1:
                menu_body = items_list[0]
            else:
                menu_body = ", ".join(items_list[:-1]) + ", " + items_list[-1]
            past = relative in ("yesterday", "day_before_yesterday") or day < now.day
            pres, past_cop = _ida_polite_copula_after(items_list[-1])
            copula = past_cop if past else pres
            return f"{date_str} 점심 메뉴는 {menu_body}{copula}! {suffix}"
        return f"{day}일 점심 메뉴 정보가 없어요."
