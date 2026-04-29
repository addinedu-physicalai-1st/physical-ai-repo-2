"""출결 조회 + robot 디바이스 face recognize / check-in/out."""
from datetime import date as DateType, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.control.auth import current_active_user
from server.control.config import settings
from server.control.deps import assert_my_child, require_device_token, require_teacher
from server.control.face_recognition import extract_embedding
from server.control.schemas import (
    AttendanceCheckPayload,
    AttendanceCheckResult,
    AttendanceRecordOut,
    FaceRecognizeResult,
)
from server.db.models import Attendance, Child, ChildFaceEmbedding, User
from server.db.session import get_session

router = APIRouter(prefix="/api", tags=["attendance"])


@router.get("/attendance", response_model=list[AttendanceRecordOut])
async def list_all_attendance(
    date: DateType = Query(...),
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_session),
) -> list[AttendanceRecordOut]:
    """전체 자녀 × 해당 날짜 출결 — 미등원 자녀는 check_in/out 모두 None."""
    children = (await session.execute(select(Child))).scalars().all()
    records = (
        await session.execute(
            select(Attendance).where(Attendance.date == date)
        )
    ).scalars().all()

    from datetime import datetime as _dt
    by_child: dict[int, dict[str, _dt | None]] = {}
    for a in records:
        slot = by_child.setdefault(a.child_id, {"IN": None, "OUT": None})
        slot[a.type] = a.time

    return [
        AttendanceRecordOut(
            child_id=c.id,
            child_name=c.name,
            check_in=by_child.get(c.id, {}).get("IN"),
            check_out=by_child.get(c.id, {}).get("OUT"),
        )
        for c in children
    ]


@router.get(
    "/children/{child_id}/attendance",
    response_model=list[AttendanceRecordOut],
)
async def list_child_attendance(
    child_id: int,
    date: Optional[DateType] = Query(None),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[AttendanceRecordOut]:
    """학부모 자녀 출결 이력 (date 옵션). 학부모는 본인 자녀만, 교사는 모든 자녀."""
    if user.role == "parent":
        await assert_my_child(child_id, user, session)
    elif user.role != "teacher":
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, "Forbidden")

    child = await session.get(Child, child_id)
    if not child:
        return []

    query = select(Attendance).where(Attendance.child_id == child_id)
    if date:
        query = query.where(Attendance.date == date)
    query = query.order_by(Attendance.date.desc(), Attendance.time)

    records = (await session.execute(query)).scalars().all()

    from datetime import datetime as _dt
    by_date: dict[DateType, dict[str, _dt | None]] = {}
    for a in records:
        slot = by_date.setdefault(a.date, {"IN": None, "OUT": None})
        slot[a.type] = a.time

    return [
        AttendanceRecordOut(
            child_id=child_id,
            child_name=child.name,
            check_in=slot.get("IN"),
            check_out=slot.get("OUT"),
        )
        for slot in by_date.values()
    ]


# ---- robot 디바이스 endpoint ----


@router.post(
    "/attendance/recognize",
    response_model=FaceRecognizeResult,
    dependencies=[Depends(require_device_token)],
)
async def recognize_face(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> FaceRecognizeResult:
    """업로드 이미지에서 얼굴 임베딩 추출 → DB 의 모든 어린이 임베딩과 cosine distance,
    threshold 이하면 가장 가까운 어린이 반환."""
    content = await file.read()
    emb = extract_embedding(content)
    if emb is None:
        return FaceRecognizeResult(matched=False)

    # pgvector 의 <=> (cosine distance) 사용 — 작은 값일수록 유사
    stmt = (
        select(
            ChildFaceEmbedding.child_id,
            Child.name,
            ChildFaceEmbedding.embedding.cosine_distance(emb).label("distance"),
        )
        .join(Child, Child.id == ChildFaceEmbedding.child_id)
        .order_by("distance")
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return FaceRecognizeResult(matched=False)

    child_id, child_name, distance = row
    if distance > settings.face_match_threshold:
        return FaceRecognizeResult(matched=False, distance=float(distance))

    return FaceRecognizeResult(
        matched=True,
        child_id=child_id,
        child_name=child_name,
        distance=float(distance),
    )


@router.post(
    "/attendance/check",
    response_model=AttendanceCheckResult,
    dependencies=[Depends(require_device_token)],
)
async def attendance_check(
    payload: AttendanceCheckPayload,
    session: AsyncSession = Depends(get_session),
) -> AttendanceCheckResult:
    """등원/하원 기록. 같은 날짜 + 같은 type 이 이미 있으면 already=True 로 반환 (중복 방지)."""
    child = await session.get(Child, payload.child_id)
    if not child:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Child not found")

    now = datetime.now(KST)
    today = now.date()

    existing = (
        await session.execute(
            select(Attendance).where(
                Attendance.child_id == payload.child_id,
                Attendance.date == today,
                Attendance.type == payload.type,
            )
        )
    ).scalar_one_or_none()

    if existing:
        return AttendanceCheckResult(
            child_id=child.id,
            child_name=child.name,
            type=existing.type,
            time=existing.time,
            already=True,
        )

    record = Attendance(
        child_id=payload.child_id,
        date=today,
        type=payload.type,
        time=now,
    )
    session.add(record)
    await session.commit()

    return AttendanceCheckResult(
        child_id=child.id,
        child_name=child.name,
        type=payload.type,
        time=now,
        already=False,
    )
