"""보고서 조회·편집."""
from datetime import date as DateType, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.control.auth import current_active_user
from server.control.deps import require_teacher
from server.control.schemas import ReportOut, ReportPatchPayload
from server.db.models import Attendance, Child, ParentChild, Report, User
from server.db.session import get_session

router = APIRouter(prefix="/api", tags=["reports"])


@router.get("/reports", response_model=list[ReportOut])
async def list_reports(
    child_id: Optional[int] = Query(None),
    date: Optional[DateType] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[ReportOut]:
    if status_filter == "pending":
        if user.role != "teacher":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Forbidden")
        if date is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "date 필요")

        attended = (
            await session.execute(
                select(Attendance.child_id)
                .where(Attendance.date == date, Attendance.type == "IN")
                .distinct()
            )
        ).scalars().all()
        reported = (
            await session.execute(
                select(Report.child_id).where(Report.date == date).distinct()
            )
        ).scalars().all()

        pending_ids = set(attended) - set(reported)

        return [
            ReportOut(
                id=10000 + cid,
                child_id=cid,
                date=date,
                content="",
                created_at=datetime.now(timezone.utc),
                updated_at=None,
            )
            for cid in sorted(pending_ids)
        ]

    if child_id is None or date is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "child_id 와 date 필요")

    if user.role == "parent":
        mapping = await session.execute(
            select(ParentChild).where(
                ParentChild.parent_id == user.id,
                ParentChild.child_id == child_id,
            )
        )
        if mapping.scalar_one_or_none() is None:
            return []

    rows = (
        await session.execute(
            select(Report).where(Report.child_id == child_id, Report.date == date)
        )
    ).scalars().all()
    return [ReportOut.model_validate(r, from_attributes=True) for r in rows]


@router.patch("/reports/{report_id}", response_model=ReportOut)
async def update_report(
    report_id: int,
    payload: ReportPatchPayload,
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_session),
) -> ReportOut:
    report = await session.get(Report, report_id)
    if not report:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    report.content = payload.content
    report.updated_at = datetime.now(timezone.utc)
    await session.commit()

    return ReportOut.model_validate(report, from_attributes=True)
