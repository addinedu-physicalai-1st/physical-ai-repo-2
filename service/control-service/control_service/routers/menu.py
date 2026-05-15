"""메뉴 조회 — day-of-month 기반."""
import calendar
from datetime import date as DateType

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control_service.auth import current_active_user
from control_service.schemas import MenuEntryOut
from control_db.models import Menu, User
from control_db.session import get_session

router = APIRouter(prefix="/api", tags=["menu"])


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
