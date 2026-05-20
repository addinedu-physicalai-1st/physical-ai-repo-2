"""유치원 등록 원아 명단 라벨.

기존 context.py 에서 이전.
- fetch_registered_children_labels() -> str | None
"""
import asyncio
import logging
import time

from sqlalchemy import select

from ai_service.config import settings as ai_settings
from control_db.models import Child
from control_db.session import async_session_maker


_roster_labels_cache: tuple[float, str | None] | None = None
_roster_labels_lock = asyncio.Lock()


async def _load_registered_children_labels_from_db(*, limit: int) -> str | None:
    from ai_service.context import child_call_name

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
