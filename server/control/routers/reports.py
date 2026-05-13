"""보고서 조회·편집·생성."""
from datetime import date as DateType, datetime, timezone, timedelta
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.control.auth import current_active_user
from server.control.config import settings
from server.control.deps import require_teacher
from server.control.routers.photos import classify_unmapped_photos_for_date
from server.control.schemas import ReportAttendanceDebugOut, ReportOut, ReportPatchPayload
from server.ai.korean_postprocess import polish_report_json_content, report_address_name
from server.db.models import Attendance, Child, Menu, ParentChild, Photo, PhotoSubject, Report, User
from server.db.session import get_session

router = APIRouter(prefix="/api", tags=["reports"])

# 보고서의 시각 표기는 KST 기준 (학부모·교사가 사람으로 읽는 시각).
_KST = timezone(timedelta(hours=9))


def _kst_hhmm(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(_KST).strftime("%H:%M")


async def fetch_attendance_debug(
    session: AsyncSession, child_id: int, day: DateType
) -> ReportAttendanceDebugOut:
    att_rows = (
        await session.execute(
            select(Attendance).where(
                Attendance.child_id == child_id,
                Attendance.date == day,
            )
        )
    ).scalars().all()
    check_in = next((r.time for r in att_rows if r.type == "IN"), None)
    check_out = next((r.time for r in att_rows if r.type == "OUT"), None)
    return ReportAttendanceDebugOut(
        has_check_in=check_in is not None,
        has_check_out=check_out is not None,
        check_in_kst=_kst_hhmm(check_in),
        check_out_kst=_kst_hhmm(check_out),
    )


def report_out_with_debug(row: Report, debug: ReportAttendanceDebugOut) -> ReportOut:
    base = ReportOut.model_validate(row, from_attributes=True)
    return base.model_copy(update={"attendance_debug": debug})


def _address_and_registered(child: Child) -> tuple[str, str | None]:
    address_name = (child.given_name or "").strip() or report_address_name(child.name)
    reg = child.name.strip()
    registered = reg if reg != address_name else None
    return address_name, registered


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

        # 일과 보고서 화면의 「대기」와 동일: 해당 일 **보고서 행이 없는** 등록 원아 전부.
        # (구버전: 등원(IN) 기록이 있는 원아만 — 미등원이면 대시보드 미작성이 항상 0건이 됨.)
        child_ids = (await session.execute(select(Child.id))).scalars().all()
        reported = (
            await session.execute(
                select(Report.child_id).where(Report.date == date).distinct()
            )
        ).scalars().all()

        pending_ids = set(child_ids) - set(reported)

        out: list[ReportOut] = []
        for cid in sorted(pending_ids):
            dbg = await fetch_attendance_debug(session, cid, date)
            out.append(
                ReportOut(
                    id=10000 + cid,
                    child_id=cid,
                    date=date,
                    content="",
                    created_at=datetime.now(timezone.utc),
                    updated_at=None,
                    attendance_debug=dbg,
                )
            )
        return out

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
    child = await session.get(Child, child_id)
    addr, reg = _address_and_registered(child) if child else ("", None)
    result: list[ReportOut] = []
    for r in rows:
        dbg = await fetch_attendance_debug(session, r.child_id, r.date)
        out = report_out_with_debug(r, dbg)
        if child:
            polished = polish_report_json_content(
                r.content, addr, reg, class_name=child.class_name
            )
            out = out.model_copy(update={"content": polished})
        result.append(out)
    return result


class GenerateReportPayload(BaseModel):
    child_id: int
    date: DateType


@router.post("/reports/generate", response_model=ReportOut)
async def generate_report(
    payload: GenerateReportPayload,
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_session),
) -> ReportOut:
    """교사가 임의 트리거 — 자녀 + 날짜의 일과 보고서를 LLM 으로 즉시 생성.

    데이터 소스: 자연 촬영 사진 메타 (`photo` 테이블, 해당 일자) + 점심메뉴
    (`menu` day-of-month) + 원 일과표 + `child` 프로필(반·생일·`given_name`/`name` 기반 호칭,
    특이사항) + 해당 일 `attendance` 등하원 시각. `mode_history` 는 미구현이라 제외. 결과는 `report`
    테이블에 UPSERT — 이미 있으면 덮어쓴다 (교사가 의도적으로 재생성).
    """
    child = await session.get(Child, payload.child_id)
    if child is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "child not found")

    today_kst = datetime.now(_KST).date()
    if payload.date > today_kst:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "report date cannot be in the future (KST)",
        )

    # 미분류 사진 back-fill — 업로드 시점에 얼굴 미검출 / 임베딩 미존재 등으로 매핑이
    # 누락된 자연 촬영 사진을 face matching 으로 채운다. 보고서 생성 트리거 = 사진 분류 트리거.
    await classify_unmapped_photos_for_date(session, payload.date)

    # 그날의 자연 촬영 사진 메타 — KST 기준 일자 + photo_subject 매핑으로 이 자녀가 등장한 사진만.
    day_start_kst = datetime.combine(payload.date, datetime.min.time(), _KST)
    day_end_kst = day_start_kst + timedelta(days=1)
    photos = (
        await session.execute(
            select(Photo)
            .join(PhotoSubject, PhotoSubject.photo_id == Photo.id)
            .where(
                PhotoSubject.child_id == payload.child_id,
                Photo.taken_at >= day_start_kst,
                Photo.taken_at < day_end_kst,
            )
            .order_by(Photo.taken_at.asc())
        )
    ).scalars().all()

    photo_events = [
        {
            "photo_id": p.id,
            "time": p.taken_at.astimezone(_KST).strftime("%H:%M"),
            "robot": p.robot or "unknown",
            "mode": p.mode or "unknown",
            "emotion": p.emotion or "neutral",
            "score": f"{p.emotion_score:.2f}" if p.emotion_score is not None else "0.00",
        }
        for p in photos
    ]

    # 점심메뉴 — day-of-month 매칭.
    menu_row = (
        await session.execute(select(Menu).where(Menu.day == payload.date.day))
    ).scalar_one_or_none()
    menu_items: list[str] = list(menu_row.items) if menu_row else []

    address_name = (child.given_name or "").strip() or report_address_name(child.name)
    registered_for_scrub = child.name.strip() if child.name.strip() != address_name else None

    att_rows = (
        await session.execute(
            select(Attendance).where(
                Attendance.child_id == payload.child_id,
                Attendance.date == payload.date,
            )
        )
    ).scalars().all()
    check_in = next((r.time for r in att_rows if r.type == "IN"), None)
    check_out = next((r.time for r in att_rows if r.type == "OUT"), None)

    attendance_payload = {
        "check_in_kst": _kst_hhmm(check_in),
        "check_out_kst": _kst_hhmm(check_out),
    }
    attendance_debug = ReportAttendanceDebugOut(
        has_check_in=check_in is not None,
        has_check_out=check_out is not None,
        check_in_kst=attendance_payload["check_in_kst"],
        check_out_kst=attendance_payload["check_out_kst"],
    )

    # AI Hub 호출.
    hub_timeout = httpx.Timeout(
        connect=10.0,
        read=settings.ai_hub_report_timeout_s,
        write=30.0,
        pool=5.0,
    )
    try:
        async with httpx.AsyncClient(timeout=hub_timeout) as client:
            r = await client.post(
                f"{settings.ai_hub_url}/report/generate",
                json={
                    "child_name": address_name,
                    "registered_full_name": child.name.strip(),
                    "class_name": child.class_name,
                    "birth_date": child.birth_date.isoformat(),
                    "date": payload.date.isoformat(),
                    "photo_events": photo_events,
                    "menu_items": menu_items,
                    "child_notes": child.notes.strip() if child.notes else None,
                    "attendance": attendance_payload,
                },
            )
            r.raise_for_status()
            content = str(r.json().get("content", "")).strip()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"AI Hub unavailable: {exc}"
        ) from exc

    if not content:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "AI Hub returned empty body")

    content = polish_report_json_content(
        content, address_name, registered_for_scrub, class_name=child.class_name
    )

    # UPSERT — UNIQUE (child_id, date) 활용.
    existing = (
        await session.execute(
            select(Report).where(
                Report.child_id == payload.child_id,
                Report.date == payload.date,
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if existing is None:
        report = Report(
            child_id=payload.child_id,
            date=payload.date,
            content=content,
            created_at=now,
            updated_at=None,
        )
        session.add(report)
    else:
        existing.content = content
        existing.updated_at = now
        report = existing
    await session.commit()
    await session.refresh(report)
    return report_out_with_debug(report, attendance_debug)


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(
    report_id: int,
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_session),
) -> None:
    """해당 일 보고서 행 삭제 — 재생성 전 초기화용."""
    report = await session.get(Report, report_id)
    if not report:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await session.delete(report)
    await session.commit()


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

    ch = await session.get(Child, report.child_id)
    if ch:
        addr, reg = _address_and_registered(ch)
        report.content = polish_report_json_content(
            payload.content, addr, reg, class_name=ch.class_name
        )
    else:
        report.content = payload.content
    report.updated_at = datetime.now(timezone.utc)
    await session.commit()

    dbg = await fetch_attendance_debug(session, report.child_id, report.date)
    return report_out_with_debug(report, dbg)
