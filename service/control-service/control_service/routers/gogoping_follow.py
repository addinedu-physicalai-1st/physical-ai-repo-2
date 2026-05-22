"""POST /api/gogoping/follow/start, /stop + GET /state.

Client → backend 로 embedding 전달 없음. backend 가 teacher_id 로 teacher_face_embedding 테이블 lookup → ROS publish.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from control_service.deps import require_teacher_or_device_token
from control_service.schemas import (
    FollowStartPayload,
    FollowStopPayload,
    FollowStateOut,
)
from control_db.models import TeacherFaceEmbedding, User
from control_db.session import get_session

router = APIRouter(prefix="/api/gogoping/follow", tags=["gogoping-follow"])

# module-level hooks — install() wires bridge methods (테스트는 monkeypatch).
publish_follow_target = None  # type: ignore
publish_follow_stop = None    # type: ignore
current_tracking_state = None # type: ignore


def install(app, bridge) -> None:
    """main.py 가 lifespan 에서 호출 — bridge 메서드를 module-level hook 에 wire 후 라우터 include."""
    global publish_follow_target, publish_follow_stop, current_tracking_state
    publish_follow_target = bridge.publish_follow_target
    publish_follow_stop = bridge.publish_follow_stop
    current_tracking_state = bridge.current_tracking_state
    app.include_router(router)


@router.post("/start", response_model=FollowStateOut)
async def follow_start(
    payload: FollowStartPayload,
    db: AsyncSession = Depends(get_session),
    _: dict = Depends(require_teacher_or_device_token),
) -> FollowStateOut:
    if publish_follow_target is None:
        raise HTTPException(503, "ROS bridge not ready")

    teacher = await db.get(User, payload.teacher_id)
    if teacher is None or teacher.role != "teacher":
        raise HTTPException(404, "Teacher not found")

    row = (
        await db.execute(
            select(TeacherFaceEmbedding)
            .where(TeacherFaceEmbedding.teacher_id == payload.teacher_id)
            .order_by(TeacherFaceEmbedding.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            409, f"Teacher '{teacher.name}' has no registered face embedding"
        )

    publish_follow_target({
        "teacher_id": str(payload.teacher_id),
        "teacher_name": teacher.name,
        "embedding": list(row.embedding),
        "ts_ms": int(time.time() * 1000),
    })
    return FollowStateOut(
        active=True,
        teacher_id=payload.teacher_id,
        teacher_name=teacher.name,
        matched=False,
    )


@router.post("/stop", response_model=FollowStateOut)
async def follow_stop(
    payload: FollowStopPayload,
    _: dict = Depends(require_teacher_or_device_token),
) -> FollowStateOut:
    if publish_follow_stop is None:
        raise HTTPException(503, "ROS bridge not ready")
    publish_follow_stop()
    return FollowStateOut(active=False)


@router.get("/state", response_model=FollowStateOut)
async def follow_state(
    _: dict = Depends(require_teacher_or_device_token),
) -> FollowStateOut:
    if current_tracking_state is None:
        return FollowStateOut(active=False)
    s = current_tracking_state()
    if s is None:
        return FollowStateOut(active=False)
    return FollowStateOut(**s)
