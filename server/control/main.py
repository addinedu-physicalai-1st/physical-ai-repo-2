"""Control Service — REST gateway."""
import os
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

app = FastAPI(title="Pingdergarten Control", version="0.1.0")

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
async def get_tts(text: str) -> Response:
    """텍스트를 음성 스트림으로 반환 (AI Hub 프록시)."""
    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_s) as client:
            response = await client.get(
                f"{settings.ai_hub_url}/voice/tts",
                params={"text": text},
            )
            response.raise_for_status()
            return Response(content=response.content, media_type="audio/mpeg")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"AI Hub TTS unavailable: {exc}") from exc


@app.post("/api/mode")
async def mode_click(req: ModeRequest) -> dict:
    """모드 셀렉터 UI 클릭."""
    return {"ok": True, "robot": req.robot, "mode": req.mode}
