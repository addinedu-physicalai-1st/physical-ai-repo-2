"""메뉴 조회 — day-of-month 기반."""
import calendar
import datetime as dt
import pathlib
from datetime import date as DateType

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.control.auth import current_active_user
from server.control.deps import require_teacher
from server.control.schemas import MenuEntryOut
from server.db.models import Menu, User
from server.db.session import get_session

router = APIRouter(prefix="/api", tags=["menu"])

PORTAL_PUBLIC_IMAGE = (
    pathlib.Path(__file__).resolve().parent.parent.parent.parent
    / "ui" / "portal-ui" / "public" / "bento.png"
)


@router.get("/menu")
async def get_menu(
    date: DateType | None = Query(None),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
    _: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
):
    """`?date=YYYY-MM-DD` → 단일 MenuEntryOut. `?month=YYYY-MM` → list[MenuEntryOut]."""
    if date is None and month is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "date 또는 month 필요")
    if date is not None and month is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "date 와 month 동시 사용 불가")

    if date is not None:
        result = await session.execute(select(Menu).where(Menu.day == date.day))
        m = result.scalar_one_or_none()
        items = m.items if m else []
        return MenuEntryOut(date=date, items=items).model_dump(mode="json")

    # month
    year, mo = map(int, month.split("-"))
    days_in_month = calendar.monthrange(year, mo)[1]

    rows = (await session.execute(select(Menu))).scalars().all()
    by_day = {m.day: m.items for m in rows}

    out: list[dict] = []
    for day in range(1, days_in_month + 1):
        if day in by_day:
            out.append(
                MenuEntryOut(date=DateType(year, mo, day), items=by_day[day]).model_dump(mode="json")
            )
    return out


@router.get("/menu/bento-prompt")
async def get_bento_prompt(
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """오늘 메뉴를 바탕으로 Ollama 가 생성한 이미지 프롬프트를 반환."""
    today = dt.date.today()
    result = await session.execute(select(Menu).where(Menu.day == today.day))
    m = result.scalar_one_or_none()
    items = m.items if m else []

    if not items:
        return {"prompt": "", "items": []}

    try:
        from server.ai.llm import generate_bento_prompt
        prompt = await generate_bento_prompt(items)
    except Exception as e:
        prompt = f"Korean school lunch bento box with {', '.join(items)}, professional food photography"

    return {"prompt": prompt, "items": items}


@router.get("/menu/bento-image-status")
async def get_bento_image_status(
    _: User = Depends(require_teacher),
) -> dict:
    """SD 로 생성된 bento.png 이미지가 오늘 생성되었는지 상태를 반환."""
    if PORTAL_PUBLIC_IMAGE.exists():
        return {"ready": True, "url": f"/bento.png?t={int(PORTAL_PUBLIC_IMAGE.stat().st_mtime)}"}
    return {"ready": False, "url": None}
