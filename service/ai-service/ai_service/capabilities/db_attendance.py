"""등하원 (Attendance) 기반 빠른 응답.

기존 context.py 에서 이전. 함수 시그니처는 유지한다.
- try_attendance_first_reply(text) -> str | None
- try_whereabouts_first_reply(text) -> str | None
"""
import logging
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from control_db.models import Attendance, Child
from control_db.session import async_session_maker


_ATTENDANCE_KEYWORDS = (
    "등원",
    "하원",
    "출석",
    "등교",
    "하교",
    "나갔",
    "갔어",
    "왔어",
    "왔니",
    "갔니",
)
_NAME_UTTERANCE_EXCLUDE = frozenset({
    "안녕",
    "안녕하세요",
    "고마워",
    "감사",
    "심심해",
    "놀자",
    "하이",
    "네",
    "응",
    "그래",
    "고고핑",
    "에듀핑",
    "노리암",
    # 단어 "이름" 은 사람 이름이 아님 — 2글자 한글 규칙 오탐 방지
    "이름",
    "성명",
})

# 한글 성씨 1~2자 + 이름 — 로봇·선생님이 부를 때는 이름(부름명) 위주
_HANGUL_ONLY = re.compile(r"^[가-힣]+$")

# "어디 있어?" 류 — DB 등하원을 먼저 볼 때 (이름+위치 질문이 LLM 만으로 흐르는 것 방지)
_WHEREABOUTS_RE = re.compile(
    r"(어딨|어디\s*있|어디야|어디\s*갔|어디가|찾아|못\s*봤|안\s*보여|안\s*보이)",
    re.UNICODE,
)
_WHEREABOUTS_SUFFIXES = (
    "어딨어",
    "어디있어",
    "어디야",
    "어디갔어",
    "어디갔니",
    "어디갔냐",
    "있니",
    "있어",
    "있어요",
    "있냐",
    "갔니",
    "갔어",
    "보여",
    "봤어",
)
_WHEREABOUTS_STOP_TOKENS = frozenset(
    {
        "어딨어",
        "어디",
        "있어",
        "있니",
        "갔어",
        "갔니",
        "알아",
        "봤어",
        "보여",
        "어디야",
        "뭐야",
        "누구",
        "얼마",
        "오늘",
        "내일",
        "지금",
        "왜",
        "어떻게",
        "뭐",
        "못",
        "안",
        "줘",
        "봐",
    }
    | _NAME_UTTERANCE_EXCLUDE
)


def _is_bare_name_attendance_utterance(user_text: str) -> bool:
    """등하원 키워드 없이 이름만 말한 경우 — LLM 대신 규칙 기반 답을 쓸 때."""
    raw = user_text.strip()
    if not raw:
        return False
    if any(k in raw for k in _ATTENDANCE_KEYWORDS):
        return False
    compact = raw.replace(" ", "")
    if compact in _NAME_UTTERANCE_EXCLUDE:
        return False
    if "안녕" in raw or "감사" in raw or "고마워" in raw:
        return False
    # "이름이뭐야", "이름뭐야" 등 이름 **질문** (4글자+) — 원아 호명 오탐 방지. 3글자 "이름X" 는 이름으로 둠
    if compact.startswith("이름") and len(compact) >= 4:
        return False
    if _HANGUL_ONLY.match(compact) and 2 <= len(compact) <= 5:
        return True
    if re.search(r"저는\s*.+", raw) or re.search(r"내\s*이름은", raw):
        return True
    return False


def _looks_like_whereabouts_query(user_text: str) -> bool:
    raw = user_text.strip()
    if not raw:
        return False
    nospace = re.sub(r"[\s?!.,…]+", "", raw)
    return bool(_WHEREABOUTS_RE.search(raw)) or bool(_WHEREABOUTS_RE.search(nospace))


def _whereabouts_name_candidates(user_text: str) -> list[str]:
    """위치 질문 문장에서 등원부 DB 매칭에 쓸 이름 후보(짧은 한글 토큰)."""
    raw = user_text.strip()
    if not raw:
        return []
    nospace = re.sub(r"[\s?!.,…]+", "", raw)
    seen: set[str] = set()
    out: list[str] = []
    for suf in _WHEREABOUTS_SUFFIXES:
        if nospace.endswith(suf) and len(nospace) > len(suf):
            pref = nospace[: -len(suf)]
            if 2 <= len(pref) <= 6 and _HANGUL_ONLY.match(pref) and pref not in _WHEREABOUTS_STOP_TOKENS:
                if pref not in seen:
                    seen.add(pref)
                    out.append(pref)
    for tok in re.findall(r"[가-힣]{2,5}", nospace):
        if tok in _WHEREABOUTS_STOP_TOKENS:
            continue
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _pick_best_db_name_from_utterance(user_nospace: str, matched: list[str]) -> str:
    if len(matched) == 1:
        return matched[0]
    raw = user_nospace.replace(" ", "")
    for n in sorted(matched, key=lambda x: len(x.replace(" ", "")), reverse=True):
        if n.replace(" ", "") in raw:
            return n
    return sorted(matched)[0]


def _format_time_kst(t: datetime, kst: ZoneInfo) -> str:
    local = t.astimezone(kst)
    ap = "오전" if local.hour < 12 else "오후"
    h12 = local.hour % 12
    if h12 == 0:
        h12 = 12
    return f"{ap} {h12}시 {local.minute}분"


def _user_matches_attendance_name(user_compact: str, db_child_name: str) -> bool:
    from ai_service.context import child_call_name

    u = user_compact.strip().replace(" ", "")
    raw = (db_child_name or "").strip().replace(" ", "")
    if not u or not raw:
        return False
    if u == raw:
        return True
    call_raw = child_call_name(raw)
    # 이름 매칭은 DB 기반 '정확 매칭'만 허용: 부분 문자열/유사어 매칭 금지
    if call_raw and u == call_raw:
        return True
    return False


def bare_name_attendance_reply(user_text: str, rows: list[tuple[str, str, datetime]]) -> str:
    """이름만 말한 경우 짧은 로봇 멘트. `rows` 는 (child_name, type, time) 정렬된 목록."""
    from ai_service.context import child_call_name

    kst = ZoneInfo("Asia/Seoul")
    compact = user_text.strip().replace(" ", "")
    if not rows:
        return "오늘 등하원 기록이 아직 없어요. 선생님께 확인해 주세요."

    matched: list[tuple[str, str, datetime]] = [
        (name, typ, t) for name, typ, t in rows if _user_matches_attendance_name(compact, name)
    ]
    if not matched:
        return "오늘 그 이름의 등하원 기록이 없어요. 선생님께 확인해 주세요."

    # 동명/부름명 충돌 시 DB 성명과 입력이 완전 일치하는 행을 우선.
    matched.sort(
        key=lambda r: (0 if r[0].strip().replace(" ", "") == compact else 1, r[0]),
    )
    db_name = matched[0][0]
    label = child_call_name(db_name)
    call = label if label else db_name

    ins_t: datetime | None = None
    out_t: datetime | None = None
    for _name, typ, t in matched:
        if typ == "IN":
            ins_t = t if ins_t is None or t < ins_t else ins_t
        elif typ == "OUT":
            out_t = t if out_t is None or t > out_t else out_t

    if ins_t and out_t:
        return (
            f"{call}야, {_format_time_kst(ins_t, kst)}에 등원하고 "
            f"{_format_time_kst(out_t, kst)}에 하원했어!"
        )
    if ins_t:
        return f"{call}야, {_format_time_kst(ins_t, kst)}에 등원했구나! 반가워!"
    if out_t:
        return f"{call}야, {_format_time_kst(out_t, kst)}에 하원 기록이 있어. 수고했어!"
    return f"{call}야, 오늘 기록을 확인했어!"


def whereabouts_attendance_reply(db_full_name: str, rows: list[tuple[str, str, datetime]]) -> str:
    """'OOO 어딨어?' 류에 맞춘 짧은 사실 답변. `rows` 는 당일 전체 등하원."""
    from ai_service.context import child_call_name

    kst = ZoneInfo("Asia/Seoul")
    dn = db_full_name.strip().replace(" ", "")
    label = child_call_name(db_full_name)
    call = label if label else db_full_name
    child_rows = [r for r in rows if r[0].strip().replace(" ", "") == dn]
    if not child_rows:
        return f"오늘 {call}의 등하원 기록이 아직 없어요. 선생님께 확인해 주세요."

    ins_t: datetime | None = None
    out_t: datetime | None = None
    for _name, typ, t in child_rows:
        if typ == "IN":
            ins_t = t if ins_t is None or t < ins_t else ins_t
        elif typ == "OUT":
            out_t = t if out_t is None or t > out_t else out_t

    if ins_t and out_t:
        return (
            f"{call}는 오늘 {_format_time_kst(ins_t, kst)}에 등원했어요. "
            f"{_format_time_kst(out_t, kst)}에 하원했어요. 지금은 유치원에 없을 수 있어요."
        )
    if ins_t:
        return (
            f"{call}는 오늘 {_format_time_kst(ins_t, kst)}에 등원했어요. "
            "지금은 아마 유치원에 있을 거예요!"
        )
    if out_t:
        return (
            f"{call}는 {_format_time_kst(out_t, kst)}에 하원했어요. "
            "지금은 유치원에 없을 수 있어요."
        )
    return f"{call}의 오늘 기록을 확인했어요. 선생님께 물어봐도 좋아요."


async def fetch_attendance_rows_kst_today() -> list[tuple[str, str, datetime]] | None:
    """KST 오늘 (child_name, IN|OUT, time). DB 오류 시 None."""
    kst = ZoneInfo("Asia/Seoul")
    today: date = datetime.now(kst).date()
    try:
        async with async_session_maker() as session:
            stmt = (
                select(Child.name, Attendance.type, Attendance.time)
                .join(Attendance, Attendance.child_id == Child.id)
                .where(Attendance.date == today)
                .order_by(Attendance.type.asc(), Attendance.time.asc())
            )
            raw_rows = list((await session.execute(stmt)).all())
    except Exception as exc:
        logging.debug("[context] attendance 조회 실패: %s", exc)
        return None
    return [(str(name), str(typ), t) for name, typ, t in raw_rows]


async def try_attendance_first_reply(user_text: str) -> str | None:
    """이름만 입력된 경우 LLM 우회 — 아이 말투 자기소개 환각 방지."""
    from ai_service.context import fetch_registered_children_names

    if not _is_bare_name_attendance_utterance(user_text):
        return None
    compact = user_text.strip().replace(" ", "")
    db_names = await fetch_registered_children_names()
    if db_names is None:
        return None
    # DB 원아명과 매칭되지 않으면 등하원 경로로 가지 않고 일반 의도/대화로 보냄.
    if not any(_user_matches_attendance_name(compact, n) for n in db_names):
        return None
    rows = await fetch_attendance_rows_kst_today()
    if rows is None:
        return "등하원 정보를 잠시 불러오지 못했어요. 선생님께 확인해 주세요."
    return bare_name_attendance_reply(user_text, rows)


async def try_whereabouts_first_reply(user_text: str) -> str | None:
    """'OOO 어딨어?' 등 — 등원부를 LLM 보다 먼저 본다."""
    from ai_service.context import fetch_registered_children_names

    if not _looks_like_whereabouts_query(user_text):
        return None
    candidates = _whereabouts_name_candidates(user_text)
    if not candidates:
        return None
    db_names = await fetch_registered_children_names()
    if db_names is None:
        return None
    matched_db: list[str] = []
    for c in candidates:
        for n in db_names:
            if _user_matches_attendance_name(c, n) and n not in matched_db:
                matched_db.append(n)
    if not matched_db:
        return None
    best = _pick_best_db_name_from_utterance(user_text.replace(" ", ""), matched_db)
    rows = await fetch_attendance_rows_kst_today()
    if rows is None:
        return "등하원 정보를 잠시 불러오지 못했어요. 선생님께 확인해 주세요."
    return whereabouts_attendance_reply(best, rows)
