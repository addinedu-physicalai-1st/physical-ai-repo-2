"""보고서 (Report) 기반 빠른 응답.

기존 context.py 에서 이전.
- try_report_first_reply(text) -> str | None
"""
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ai_service.capabilities.db_attendance import (
    _WHEREABOUTS_STOP_TOKENS,
    _pick_best_db_name_from_utterance,
    _user_matches_attendance_name,
)
from control_db.models import Child, Report
from control_db.session import async_session_maker


_HANGUL_ONLY = re.compile(r"^[가-힣]+$")

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


async def fetch_today_report_content_for_db_name(db_full_name: str) -> tuple[str | None, bool]:
    """오늘(KST) 해당 원아 `report.content`. (내용 또는 None, DB_실패여부)."""
    kst = ZoneInfo("Asia/Seoul")
    today = datetime.now(kst).date()
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
    from ai_service.context import child_call_name, fetch_registered_children_names

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
