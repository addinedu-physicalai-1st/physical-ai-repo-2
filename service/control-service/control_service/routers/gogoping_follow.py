"""POST /api/gogoping/follow/start, /stop + GET /state + WS /ws/tracking-state.

Client → backend 로 embedding 전달 없음. backend 가 teacher_id 로 teacher_face_embedding 테이블 lookup → ROS publish.
"""
import asyncio
import logging
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gogoping/follow", tags=["gogoping-follow"])


class FollowHintIn(BaseModel):
    """디버그 패널 → /gogoping/follow_hint 발행.

    - left/right/front/back: WAITING_HINT 모드용
    - search: VOICE_SEARCH 진입 (음성 "고고핑 추종 위치확인")
    - resume: VOICE_RESUME 진입 (음성 "고고핑 추종 위치이동")
    """
    direction: Literal["left", "right", "front", "back", "search", "resume"]


# module-level hooks — install() wires bridge methods (테스트는 monkeypatch).
publish_follow_target = None  # type: ignore
publish_follow_stop = None    # type: ignore
publish_follow_hint = None    # type: ignore
current_tracking_state = None # type: ignore
_bridge = None  # type: ignore


def install(app, bridge) -> None:
    """main.py 가 lifespan 에서 호출 — bridge 메서드를 module-level hook 에 wire 후 라우터 include."""
    global publish_follow_target, publish_follow_stop, publish_follow_hint
    global current_tracking_state, _bridge
    publish_follow_target = bridge.publish_follow_target
    publish_follow_stop = bridge.publish_follow_stop
    publish_follow_hint = bridge.publish_follow_hint
    current_tracking_state = bridge.current_tracking_state
    _bridge = bridge
    app.include_router(router)
    _install_tracking_state_ws(app, bridge)
    _install_follow_state_ws(app, bridge)


@router.post("/hint")
async def follow_hint(payload: FollowHintIn) -> dict:
    """디버그용 — WAITING_HINT 모드에 hint 발행. STT 미연동 시 UI 에서 직접 호출."""
    if publish_follow_hint is None:
        raise HTTPException(503, "ROS bridge not ready")
    try:
        publish_follow_hint(payload.direction)
    except Exception as exc:
        raise HTTPException(503, f"publish failed: {exc}") from exc
    return {"ok": True, "published": payload.direction}


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
    if _bridge is not None:
        _bridge.publish_admin_event(
            "follow_start", f"teacher={teacher.name!r}",
        )
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
    if _bridge is not None:
        _bridge.publish_admin_event("follow_stop")
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


def _install_follow_state_ws(app, bridge) -> None:
    """``/ws/follow-state`` WebSocket — bridge 의 /gogoping/follow_state fan-out (mode 전이 시)."""

    @app.websocket("/ws/follow-state")
    async def follow_state_ws(ws: WebSocket) -> None:
        await ws.accept()
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=16)

        def _on_state(mode: str) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, mode)
            except asyncio.QueueFull:
                pass

        unreg = bridge.register_follow_state_callback(_on_state)

        # 연결 즉시 latest mode — 새 클라이언트가 늦게 붙어도 즉시 표시
        latest = bridge.current_follow_state()
        if latest is not None:
            await ws.send_json({"mode": latest})

        try:
            while True:
                mode = await queue.get()
                await ws.send_json({"mode": mode})
        except WebSocketDisconnect:
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning(f"follow-state WS 오류: {e}")
        finally:
            unreg()


def _install_tracking_state_ws(app, bridge) -> None:
    """``/ws/tracking-state`` WebSocket — bridge 의 /gogoping/tracking_state fan-out (5 Hz)."""

    @app.websocket("/ws/tracking-state")
    async def tracking_state_ws(ws: WebSocket) -> None:
        await ws.accept()
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=10)

        def _on_state(payload: dict) -> None:
            # ros spin thread 에서 호출 — main loop 의 queue 에 thread-safe put
            try:
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            except asyncio.QueueFull:
                # 클라이언트가 느리면 drop — 5 Hz publish 의 다음 메시지로 회복
                pass

        unreg = bridge.register_tracking_state_callback(_on_state)

        # 연결 즉시 latest state 보냄 — 새 클라이언트가 늦게 붙어도 즉시 표시
        latest = bridge.current_tracking_state()
        if latest is not None:
            await ws.send_json(latest)

        try:
            while True:
                payload = await queue.get()
                await ws.send_json(payload)
        except WebSocketDisconnect:
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning(f"tracking-state WS 오류: {e}")
        finally:
            unreg()
