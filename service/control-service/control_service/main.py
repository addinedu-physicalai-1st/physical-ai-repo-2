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

from control_service.auth import (
    UserCreate,
    UserRead,
    UserUpdate,
    cookie_backend,
    fastapi_users,
)
from control_service.config import settings
from control_service.routers import attendance as attendance_router
from control_service.routers import children as children_router
from control_service.routers import menu as menu_router
from control_service.routers import parents as parents_router
from control_service.routers import photos as photos_router
from control_service.routers import reports as reports_router
from control_service.routers import schedule as schedule_router
from control_service.routers import voice as voice_router
from control_service.camera_pan.ros_bridge import CameraPanBridge
from control_service.camera_pan.router import install as install_camera_pan
from control_service.teleop.ros_bridge import RosBridge
from control_service.teleop.router import install as install_teleop
from control_service.waypoints.ros_bridge import WaypointsRosBridge
from control_service.waypoints.router import install as install_waypoints

logger = logging.getLogger(__name__)

# noriarm_framework 의 매니페스트 경로 — Control Server 가 같은 게임 정의를 공유한다.
_NORIARM_OX_MANIFEST = (
    Path(__file__).resolve().parents[3]
    / "controller"
    / "noriarm-controller"
    / "src"
    / "noriarm_framework"
    / "noriarm_framework"
    / "games"
    / "ox_quiz"
    / "game.yaml"
)

# eduping (OpenArm) 율동/인사 routine 저장소 — repo_root/shared/.
_SHARED_DIR = Path(__file__).resolve().parents[3] / "shared"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """ROS bridge lifecycle. ROS 환경 미source 시 graceful skip — noriarm/eduping 엔드포인트만 503.

    Vision (YOLO) 추론은 AI Hub (service/ai-service/ai_service/hub.py) 가 담당 — Control Server 는 proxy.

    teleop / noriarm bridge 는 모두 이 안에서 시작·종료한다. `lifespan` 이 지정된
    FastAPI app 에서는 @app.on_event 데코레이터가 동작하지 않으므로 혼용 금지.
    """
    # STT 모델 백그라운드 warm-up — 첫 요청이 ~30s 걸리는 cold start 회피.
    # 다운로드 + 로드 실패해도 routing 영향 없음, 첫 요청 시 다시 시도됨.
    try:
        from ai_service import stt as _stt_engine

        asyncio.create_task(asyncio.to_thread(_stt_engine._get_model))
        logger.info("STT 모델 warm-up 시작 (background)")
    except Exception as e:
        logger.warning(f"STT warm-up 스케줄 실패: {e}")

    try:
        _teleop_bridge.start()
    except Exception as e:
        logger.warning(f"teleop RosBridge 시작 실패: {e}")

    try:
        _waypoints_bridge.start()
    except Exception as e:
        logger.warning(f"waypoints RosBridge 시작 실패: {e}")

    try:
        _camera_pan_bridge.start()
    except Exception as e:
        logger.warning(f"camera_pan RosBridge 시작 실패: {e}")

    try:
        await _teleop_hub.start()
    except Exception as e:
        logger.warning(f"teleop hub 시작 실패: {e}")

    try:
        await _camera_pan_hub.start()
    except Exception as e:
        logger.warning(f"camera_pan hub 시작 실패: {e}")

    noriarm_bridge = None
    eduping_bridge = None
    eduping_hubs_started = False

    # --- NoriArm ---------------------------------------------------------
    try:
        from control_service.noriarm.ros_bridge import (
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
                noriarm_bridge = NoriarmRosBridge(_NORIARM_OX_MANIFEST)
                noriarm_bridge.start(asyncio.get_running_loop())
                app.state.noriarm_bridge = noriarm_bridge
                logger.info("NoriArm ROS bridge 활성화됨")
            except BridgeUnavailable as e:
                logger.warning(f"NoriArm bridge 초기화 실패: {e}")
    except ImportError as e:
        logger.warning(f"noriarm 모듈 import 실패: {e}")

    # --- Eduping (OpenArm) ----------------------------------------------
    try:
        from control_service.eduping.ros_bridge import (
            BridgeUnavailable as EdupingBridgeUnavailable,
            EdupingRosBridge,
            ros_available as eduping_ros_available,
        )
        from control_service.eduping.router import start_hubs as start_eduping_hubs

        if not eduping_ros_available():
            logger.warning(
                "ROS import 실패 — /api/eduping/* 엔드포인트는 503 으로 응답합니다."
            )
        elif not _SHARED_DIR.is_dir():
            logger.warning(f"shared/ 디렉토리 없음: {_SHARED_DIR}")
        else:
            try:
                eduping_bridge = EdupingRosBridge(_SHARED_DIR)
                eduping_bridge.start(asyncio.get_running_loop())
                await start_eduping_hubs(app, eduping_bridge)
                eduping_hubs_started = True
                logger.info("Eduping ROS bridge 활성화됨")
            except EdupingBridgeUnavailable as e:
                logger.warning(f"Eduping bridge 초기화 실패: {e}")
    except ImportError as e:
        logger.warning(f"eduping 모듈 import 실패: {e}")

    yield

    if eduping_hubs_started:
        from control_service.eduping.router import stop_hubs as stop_eduping_hubs

        await stop_eduping_hubs()
    if eduping_bridge is not None:
        eduping_bridge.stop()
    if noriarm_bridge is not None:
        noriarm_bridge.stop()
    try:
        await _teleop_hub.stop()
    except Exception:
        pass
    try:
        await _camera_pan_hub.stop()
    except Exception:
        pass
    try:
        _teleop_bridge.shutdown()
    except Exception:
        pass
    try:
        _waypoints_bridge.shutdown()
    except Exception:
        pass
    try:
        _camera_pan_bridge.shutdown()
    except Exception:
        pass


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
app.include_router(voice_router.router)

# teleop (GogoPing keyboard control) — POST /teleop/cmd_vel, WS /teleop/state, GET /teleop/health
# install_teleop 가 라우터를 부착하고 hub 를 반환한다. 실제 start/stop 은 lifespan 에서.
_teleop_bridge = RosBridge()
_teleop_hub = install_teleop(app, _teleop_bridge)

# waypoints (GogoPing waypoint Goto / patrol) — REST + SSE
_waypoints_bridge = WaypointsRosBridge()
install_waypoints(app, _waypoints_bridge)

# camera_pan (GogoPing 2-axis camera servo) — POST /camera_pan/cmd, WS /camera_pan/state
_camera_pan_bridge = CameraPanBridge()
_camera_pan_hub = install_camera_pan(app, _camera_pan_bridge)


# NoriArm — ROS 미설정 환경에서도 import 자체는 성공해야 하므로 lazy 처리.
try:
    from control_service.noriarm.router import router as noriarm_router

    app.include_router(noriarm_router)
except ImportError as e:
    logger.warning(f"noriarm router 등록 실패 — endpoint 비활성: {e}")

# Eduping (OpenArm) — bridge 미가동 시 503 자동 응답. 라우터 자체는 항상 등록.
try:
    from control_service.eduping.router import register_router as register_eduping_router

    register_eduping_router(app)
except ImportError as e:
    logger.warning(f"eduping router 등록 실패 — endpoint 비활성: {e}")

# 얼굴 이미지 정적 노출 — DB 의 photo_url 은 /api/face-images/{child_id}/{idx}.jpg 형태로 저장된다.
os.makedirs(settings.face_image_dir, exist_ok=True)
app.mount(
    "/api/face-images",
    StaticFiles(directory=settings.face_image_dir),
    name="face-images",
)

# 자연 촬영 사진 정적 노출 — photos.py 의 url 컬럼이 /api/photos-static/natural/... 형태로 저장된다.
os.makedirs(settings.photo_dir, exist_ok=True)
app.mount(
    "/api/photos-static",
    StaticFiles(directory=settings.photo_dir),
    name="photos-static",
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
