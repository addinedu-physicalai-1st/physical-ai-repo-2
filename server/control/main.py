"""Control Service — REST gateway."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from server.control.auth import (
    UserCreate,
    UserRead,
    UserUpdate,
    cookie_backend,
    fastapi_users,
)
from server.control.config import settings
from server.control.routers import attendance as attendance_router
from server.control.routers import children as children_router
from server.control.routers import menu as menu_router
from server.control.routers import parents as parents_router
from server.control.routers import photos as photos_router
from server.control.routers import reports as reports_router
from server.control.routers import schedule as schedule_router
from server.control.teleop.ros_bridge import RosBridge
from server.control.teleop.router import install as install_teleop

logger = logging.getLogger(__name__)

# noriarm_framework 의 매니페스트 경로 — Control Server 가 같은 게임 정의를 공유한다.
_NORIARM_OX_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "device"
    / "noriarm_ws"
    / "src"
    / "noriarm_framework"
    / "noriarm_framework"
    / "games"
    / "ox_quiz"
    / "game.yaml"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """ROS bridge lifecycle. ROS 환경 미source 시 graceful skip — noriarm 엔드포인트만 503.

    Vision (YOLO) 추론은 AI Hub (server/ai/hub.py) 가 담당 — Control Server 는 proxy.
    """
    bridge = None
    try:
        from server.control.noriarm.ros_bridge import (
            BridgeUnavailable,
            NoriarmRosBridge,
            ros_available,
        )

        if not ros_available():
            logger.warning(
                "ROS (rclpy / sensor_msgs) import 실패 — /api/noriarm/* 엔드포인트는 503 으로 응답합니다. "
                "활성화하려면 `source /opt/ros/jazzy/setup.bash` 후 서버 재시작."
            )
        elif not _NORIARM_OX_MANIFEST.is_file():
            logger.warning(f"OX 매니페스트 없음: {_NORIARM_OX_MANIFEST}")
        else:
            try:
                bridge = NoriarmRosBridge(_NORIARM_OX_MANIFEST)
                bridge.start(asyncio.get_running_loop())
                app.state.noriarm_bridge = bridge
                logger.info("NoriArm ROS bridge 활성화됨")
            except BridgeUnavailable as e:
                logger.warning(f"NoriArm bridge 초기화 실패: {e}")
    except ImportError as e:
        logger.warning(f"noriarm 모듈 import 실패: {e}")

    yield

    if bridge is not None:
        bridge.stop()


app = FastAPI(title="Pingdergarten Control", version="0.1.0", lifespan=lifespan)

# fastapi-users 라우터
app.include_router(
    fastapi_users.get_auth_router(cookie_backend),
    prefix="/api/auth/cookie",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/api/users",
    tags=["users"],
)
app.include_router(children_router.router)
app.include_router(parents_router.router)
app.include_router(attendance_router.router)
app.include_router(menu_router.router)
app.include_router(photos_router.router)
app.include_router(reports_router.router)
app.include_router(schedule_router.router)

# teleop (GogoPing keyboard control) — POST /teleop/cmd_vel, WS /teleop/state, GET /teleop/health
_teleop_bridge = RosBridge()
install_teleop(app, _teleop_bridge)


@app.on_event("startup")
async def _start_teleop_bridge() -> None:
    # ROS_DOMAIN_ID (201~219) 가 설정되어 있어야 한다.
    _teleop_bridge.start()


@app.on_event("shutdown")
async def _stop_teleop_bridge() -> None:
    _teleop_bridge.shutdown()


# NoriArm — ROS 미설정 환경에서도 import 자체는 성공해야 하므로 lazy 처리.
try:
    from server.control.noriarm.router import router as noriarm_router

    app.include_router(noriarm_router)
except ImportError as e:
    logger.warning(f"noriarm router 등록 실패 — endpoint 비활성: {e}")

# 얼굴 이미지 정적 노출 — DB 의 photo_url 은 /api/face-images/{child_id}/{idx}.jpg 형태로 저장된다.
os.makedirs(settings.face_image_dir, exist_ok=True)
app.mount(
    "/api/face-images",
    StaticFiles(directory=settings.face_image_dir),
    name="face-images",
)


class VoiceIntentRequest(BaseModel):
    text: str = Field(..., min_length=1)
    robot: Literal["eduping", "gogoping", "noriarm"]
    class_roster: list[str] = Field(default_factory=list, max_length=40)


class ModeRequest(BaseModel):
    robot: Literal["eduping", "gogoping", "noriarm"]
    mode: str


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/api/voice/intent")
async def voice_intent(req: VoiceIntentRequest) -> dict:
    """브라우저 발화 → AI Hub 의도 분류 → 결과 반환."""
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
            response = await client.post(
                f"{settings.ai_hub_url}/voice/intent",
                json=req.model_dump(),
            )
            response.raise_for_status()
            result: dict = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"AI Hub unavailable: {exc}") from exc

    return result


@app.get("/api/voice/tts")
async def get_tts(text: str):
    """Robot UI TTS — AI Hub Edge neural MP3."""
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
            response = await client.get(
                f"{settings.ai_hub_url}/voice/tts",
                params={"text": text},
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"AI Hub TTS unavailable: {exc}") from exc

    media_type = response.headers.get("content-type", "audio/mpeg")
    return Response(content=response.content, media_type=media_type)


@app.post("/api/mode")
async def mode_click(req: ModeRequest) -> dict:
    """모드 셀렉터 UI 클릭."""
    return {"ok": True, "robot": req.robot, "mode": req.mode}
