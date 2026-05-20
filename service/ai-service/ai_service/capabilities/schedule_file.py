"""일과표 (shared/school_schedule.json) 기반 빠른 응답.

기존 context.py 에서 이전.
- try_schedule_first_reply(text) -> str | None
- load_school_schedule_dict() -> dict
"""
import json
import logging
import re
from pathlib import Path


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
    shared_path = Path(__file__).parent.parent.parent.parent.parent / "shared" / "school_schedule.json"
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
