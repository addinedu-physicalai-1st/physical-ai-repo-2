"""출결 조회 + robot 디바이스 face recognize / check-in/out."""
import asyncio
import logging
from datetime import date as DateType, datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status as http_status
from sqlalchemy import delete, select
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

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["attendance"])

# 신규 등하원 체크 시 실물 팔로워가 자동 재생할 슬러그. 새 슬러그를 만들고 싶으면
# shared/openarm_greeting/<slug>.yaml 으로 녹화 후 여기 매핑만 바꾸면 됨.
_GREETING_SLUG_BY_ATTENDANCE_TYPE: dict[str, str] = {
    "IN": "morning",
    "OUT": "evening",
}


def _fire_attendance_greeting(request: Request, attendance_type: str) -> str:
    """첫 등/하원 기록 직후 실물 팔로워에서 인사 모션을 background 로 트리거.

    동기 preflight 결과를 문자열로 반환해 응답에 노출 → robot-ui 가 교사에게 즉시 사유를 보여줌.
    Preflight 통과(`fired`) 후의 actual playback 실패(action server 무응답 등)는 여전히 log only.

    반환 값:
      - "fired"                        : preflight 통과 + background task schedule 됨
      - "skipped:no_bridge"             : eduping bridge 미초기화 (control server 가 ROS 없이 떠있음)
      - "skipped:unknown_type"          : 알 수 없는 attendance type
      - "skipped:routine_missing:<slug>": shared/openarm_greeting/<slug>.yaml 부재
      - "skipped:no_real_arm"           : tmux eduping-device 세션에 hardware_type=real bringup 없음
    """
    bridge = getattr(request.app.state, "eduping_bridge", None)
    slug = _GREETING_SLUG_BY_ATTENDANCE_TYPE.get(attendance_type)
    if bridge is None:
        logger.debug("attendance greeting skipped — bridge not initialized")
        return "skipped:no_bridge"
    if slug is None:
        logger.debug("attendance greeting skipped — unknown type %r", attendance_type)
        return "skipped:unknown_type"

    # Preflight — routine YAML 존재 여부. `eduarm.routines_io.greeting_yaml_path` 와 동일한
    # 경로 규칙을 inline. ROS 환경 import 를 동기 경로에서 피하기 위함 (테스트 환경 + 503 friendly).
    routines_root = getattr(bridge, "routines_root", None)
    if routines_root is None:
        return f"skipped:routine_missing:{slug}"
    if not (Path(routines_root) / "openarm_greeting" / f"{slug}.yaml").exists():
        return f"skipped:routine_missing:{slug}"

    # 실물 팔로워(=openarm bringup) 가 떠있지 않으면 action goal 이 무응답으로 끝나니
    # 미리 차단해 교사에게 명확히 알려준다. is_real_follower_active() 는 3 초 TTL 캐시.
    is_real_active = getattr(bridge, "is_real_follower_active", None)
    if callable(is_real_active):
        try:
            if not is_real_active():
                return "skipped:no_real_arm"
        except Exception as exc:  # noqa: BLE001
            logger.debug("is_real_follower_active probe failed: %s", exc)
            # probe 실패는 차단 사유가 아님 — 그냥 시도해보자.

    async def _run() -> None:
        from server.control.eduping.ros_bridge import KIND_GREETING

        try:
            await asyncio.to_thread(
                bridge.play_routine, KIND_GREETING, slug, target="real"
            )
        except Exception as exc:  # noqa: BLE001
            # FileNotFoundError(레이스 시), BridgeUnavailable, ValueError 등 모두 흡수.
            logger.warning(
                "attendance greeting playback failed (slug=%s type=%s): %s",
                slug, attendance_type, exc,
            )

    asyncio.create_task(_run())
    return "fired"


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
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AttendanceCheckResult:
    """등원/하원 기록. 같은 날짜 + 같은 type 이 이미 있으면 already=True 로 반환 (중복 방지).

    첫 기록일 때 실물 팔로워에서 등원=morning / 하원=evening 인사 모션을 background 로 재생.
    """
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

    arm_status = _fire_attendance_greeting(request, payload.type)

    return AttendanceCheckResult(
        child_id=child.id,
        child_name=child.name,
        type=payload.type,
        time=now,
        already=False,
        arm_status=arm_status,
    )


@router.delete(
    "/attendance/{child_id}",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def delete_attendance(
    child_id: int,
    date: DateType = Query(..., description="삭제 대상 일자 (YYYY-MM-DD)"),
    type: Literal["IN", "OUT"] = Query(..., description="삭제 대상 출결 종류"),
    _: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_session),
) -> None:
    """교사 디버그용 — 특정 자녀의 (date, type) 출결 row 한 건 삭제.

    재테스트(특히 등/하원 인사 모션 재트리거)를 위해 노출. 같은 (child, date, type)
    조합이 없으면 404. 멱등성 위반은 신경 안 쓰고 명확히 알려준다.
    """
    result = await session.execute(
        delete(Attendance)
        .where(
            Attendance.child_id == child_id,
            Attendance.date == date,
            Attendance.type == type,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Attendance record not found")
    await session.commit()
