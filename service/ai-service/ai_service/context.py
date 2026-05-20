"""LLM 응답 시 사실 근거로 주입할 컨텍스트 모음 — RAG.

점심 메뉴는 pgvector 기반 의미 검색 (Menu.embedding, bge-m3 1024d).
쿼리에 "오늘/내일/어제" 같은 상대 날짜 토큰이 있으면 day 숫자로 치환한 뒤 임베딩.
"""
import asyncio
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ai_service.config import settings as ai_settings
from ai_service.embed import EmbedError, embed_text
from ai_service.robots import capabilities_for
from control_db.models import Attendance, Child, Menu, Report
from control_db.session import async_session_maker

_roster_labels_cache: tuple[float, str | None] | None = None
_roster_labels_lock = asyncio.Lock()

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


async def _load_registered_children_labels_from_db(*, limit: int) -> str | None:
    try:
        async with async_session_maker() as session:
            result = await session.execute(
                select(Child.name).order_by(Child.class_name, Child.name).limit(200)
            )
            rows = list(result.scalars().all())
    except Exception as exc:
        logging.debug("[context] 원아 명단 DB 조회 실패 (무시): %s", exc)
        return None

    if not rows:
        return None

    seen: set[str] = set()
    labels: list[str] = []
    for raw in rows:
        label = child_call_name(raw)
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
        if len(labels) >= limit:
            break

    return ", ".join(labels) if labels else None


async def fetch_registered_children_labels(*, limit: int = 40) -> str | None:
    """`child` 테이블에서 이름을 읽어 부름명으로 바꾼 뒤 쉼표 목록 문자열로 반환. DB 없으면 None."""
    ttl = ai_settings.roster_labels_cache_ttl_s
    if ttl <= 0:
        return await _load_registered_children_labels_from_db(limit=limit)

    global _roster_labels_cache
    async with _roster_labels_lock:
        now = time.monotonic()
        if _roster_labels_cache is not None:
            ts, val = _roster_labels_cache
            if now - ts < ttl:
                return val
        out = await _load_registered_children_labels_from_db(limit=limit)
        _roster_labels_cache = (time.monotonic(), out)
        return out


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

_REPORT_QUERY_TOKENS = (
    "보고서",
    "일일보고",
    "알림장",
    "원생일지",
    "일과보고",
    "교사일지",
)
_REPORT_NAME_SUFFIXES = (
    "일일보고",
    "원생일지",
    "알림장",
    "보고서",
    "일지",
    "일과",
)
# '알려' 단독은 "일과표 알려줘" 가 일일보고로 오탐되므로 넣지 않음 (보고서/알림장 토큰으로 커버)
_REPORT_EXTRA_VERBS = ("어땠", "뭐했", "내용", "적었", "썼", "읽어", "보여")


def _looks_like_report_query(user_text: str) -> bool:
    raw = user_text.strip()
    if not raw:
        return False
    compact = raw.replace(" ", "")
    # 일과**표**·시간표 = 하루 일정 질문 — 일일보고(report) 와 분리
    if any(x in compact for x in ("일과표", "시간표", "일정표", "학교일정", "하루일정")):
        return False
    if any(t in raw for t in _REPORT_QUERY_TOKENS):
        return True
    rest = raw
    for hide in ("일과표", "시간표", "일정표"):
        rest = rest.replace(hide, "")
    if "일과" in rest and any(w in rest for w in _REPORT_EXTRA_VERBS):
        return True
    return False


_SCHEDULE_EXCLUDE_COMPACT = ("일과보고", "일일보고", "보고서", "알림장", "원생일지", "교사일지")


def _looks_like_schedule_query(user_text: str) -> bool:
    """일과표·시간표 등 — shared/school_schedule.json 규칙 경로."""
    raw = user_text.strip()
    if not raw:
        return False
    c = re.sub(r"[\s?!.,…]+", "", raw)
    if any(x in c for x in _SCHEDULE_EXCLUDE_COMPACT):
        return False
    if any(x in c for x in ("일과표", "시간표", "일정표", "학교일정", "하루일정", "스케줄")):
        return True
    if "일정" in c and ("알려" in c or "말해" in c):
        return True
    if "일과" in c and ("알려" in c or "말해" in c) and "표" not in c:
        return True
    return False


def load_school_schedule_dict() -> dict[str, str] | None:
    """`shared/school_schedule.json` → 시간대: 활동. 실패 시 None."""
    shared_path = Path(__file__).parent.parent.parent.parent / "shared" / "school_schedule.json"
    try:
        with open(shared_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        out: dict[str, str] = {}
        for k, v in data.items():
            ks, vs = str(k).strip(), str(v).strip()
            if ks and vs:
                out[ks] = vs
        return out or None
    except Exception as exc:
        logging.error("[context] schedule 로드 실패: %s", exc)
        return None


def schedule_spoken_reply(schedule: dict[str, str]) -> str:
    """유치원 말투로 일과표 나열 (짧게)."""
    if not schedule:
        return "일과표 내용이 아직 없어요. 선생님께 확인해 주세요."
    parts = [f"{slot}에는 {label}" for slot, label in schedule.items()]
    return "일과표 알려줄게! " + " ".join(parts) + "."


def try_schedule_first_reply(user_text: str) -> str | None:
    """일과표·시간표 질문 — LLM 없이 JSON 일정을 읽어 답한다."""
    if not _looks_like_schedule_query(user_text):
        return None
    sched = load_school_schedule_dict()
    if sched is None:
        return "일과표를 잠시 불러오지 못했어요. 선생님께 확인해 주세요."
    return schedule_spoken_reply(sched)


def _report_name_candidates(user_text: str) -> list[str]:
    """보고서 질문에서 원아명 후보."""
    raw = user_text.strip()
    if not raw:
        return []
    nospace = re.sub(r"[\s?!.,…]+", "", raw)
    seen: set[str] = set()
    out: list[str] = []
    for suf in _REPORT_NAME_SUFFIXES:
        if nospace.endswith(suf) and len(nospace) > len(suf):
            pref = nospace[: -len(suf)]
            if 2 <= len(pref) <= 6 and _HANGUL_ONLY.match(pref) and pref not in _WHEREABOUTS_STOP_TOKENS:
                if pref not in seen:
                    seen.add(pref)
                    out.append(pref)
    for tok in re.findall(r"[가-힣]{2,5}", nospace):
        if tok in _WHEREABOUTS_STOP_TOKENS:
            continue
        if any(tok.endswith(s) for s in _REPORT_NAME_SUFFIXES if len(tok) > len(s)):
            continue
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


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


def _format_time_kst(t: datetime, kst: ZoneInfo) -> str:
    local = t.astimezone(kst)
    ap = "오전" if local.hour < 12 else "오후"
    h12 = local.hour % 12
    if h12 == 0:
        h12 = 12
    return f"{ap} {h12}시 {local.minute}분"


def _user_matches_attendance_name(user_compact: str, db_child_name: str) -> bool:
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


async def fetch_today_report_content_for_db_name(db_full_name: str) -> tuple[str | None, bool]:
    """오늘(KST) 해당 원아 `report.content`. (내용 또는 None, DB_실패여부)."""
    kst = ZoneInfo("Asia/Seoul")
    today: date = datetime.now(kst).date()
    name_key = db_full_name.strip()
    try:
        async with async_session_maker() as session:
            stmt = (
                select(Report.content)
                .join(Child, Report.child_id == Child.id)
                .where(Child.name == name_key, Report.date == today)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
    except Exception as exc:
        logging.debug("[context] report 조회 실패: %s", exc)
        return None, True
    if row is None:
        return None, False
    s = str(row).strip()
    return (s if s else None), False


async def report_utterance_branch(user_text: str) -> tuple[str | None, str | None]:
    """보고서/일과 질문 처리.

    반환: (규칙 기반 즉답 또는 None, LLM용 DB 안내 문구 또는 None).
    한 원아만 확실히 매칭되면 DB 를 읽어 즉답을 주고 LLM 은 거치지 않는다.
    """
    if not _looks_like_report_query(user_text):
        return None, None
    candidates = _report_name_candidates(user_text)
    db_names = await fetch_registered_children_names()
    if db_names is None:
        return None, (
            "원아 명단(DB)을 지금 읽지 못했습니다. 일일보고·보고서 내용을 지어내지 말고 "
            "선생님 화면에서 확인하라고 짧게 안내하세요."
        )
    matched_db: list[str] = []
    for c in candidates:
        for n in db_names:
            if _user_matches_attendance_name(c, n) and n not in matched_db:
                matched_db.append(n)
    if not matched_db:
        return None, (
            "보고서·일과 질문입니다. 등록된 원아 **이름을 한 명** 말해야 DB 내용을 인용할 수 있습니다. "
            "이름이 문장에 없으므로 구체 문장을 만들지 말고, 어떤 친구 보고서인지 물어보세요."
        )
    if len(matched_db) > 1:
        labels = [child_call_name(n) or n for n in sorted(matched_db)[:6]]
        return None, (
            "보고서 질문인데 여러 원아가 겹칩니다: "
            + ", ".join(labels)
            + ". 한 명만 정하게 한 뒤 다시 물어보세요. 지금은 내용을 추측하지 마세요."
        )
    best = _pick_best_db_name_from_utterance(user_text.replace(" ", ""), matched_db)
    content, err = await fetch_today_report_content_for_db_name(best)
    if err:
        return "보고서를 잠시 불러오지 못했어요. 선생님께 확인해 주세요.", None
    call = child_call_name(best) or best
    if not content:
        return f"{call} 오늘 보고서는 아직 비어 있거나 선생님이 안 썼어요.", None
    body = content.replace("\n", " ").strip()
    if len(body) > 400:
        body = body[:400].rstrip() + "…"
    return f"{call} 오늘 보고서에는 이렇게 적혀 있어요. {body}", None


async def try_report_first_reply(user_text: str) -> str | None:
    """보고서 질문 — 원아 한 명이 확실할 때 LLM 없이 DB 본문을 읽어 준다."""
    fast, _note = await report_utterance_branch(user_text)
    return fast


async def fetch_attendance_summary_kst_today() -> str | None:
    """KST 기준 오늘 등·하원 요약 한 줄. DB 실패 시 None."""
    kst = ZoneInfo("Asia/Seoul")
    today: date = datetime.now(kst).date()
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
