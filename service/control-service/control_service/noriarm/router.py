"""NoriArm REST + SSE 엔드포인트.

- POST /api/noriarm/games/ox-quiz/answer  — 답 (O/X) 을 받아 trajectory 재생 트리거
- GET  /api/noriarm/joint-states/stream   — `/joint_states` 를 SSE 로 forward (three.js 뷰어용)
- GET  /api/noriarm/info                  — bridge 상태 + 현재 게임 정보 (디버깅용)

Bridge 인스턴스는 main.py 의 lifespan 에서 생성·소멸되며, app.state.noriarm_bridge 로
참조한다. ROS 환경 미source 시 503 응답.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncIterator, Literal

import cv2
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import httpx
import websockets
from fastapi import WebSocket, WebSocketDisconnect
from urllib.parse import urlparse, urlunparse

from control_service.config import settings
from control_service.noriarm.front_camera import front_camera
from control_service.noriarm.block_stacking import router as block_stacking_router
from control_service.noriarm.store_play import router as store_play_router
from control_service.noriarm.ros_bridge import NoriarmRosBridge, ros_available

# 실물 OMX-F follower 가 udev 룰로 만든 심볼릭 링크. 존재 여부로 연결 판정.
REAL_ARM_DEV = Path("/dev/omx_follower")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/noriarm", tags=["noriarm"])
router.include_router(block_stacking_router)
router.include_router(store_play_router)

async def _mjpeg_gen() -> AsyncIterator[bytes]:
    # 공유 카메라에서 프레임을 가져온다 — rps_detector 와 디바이스를 다투지 않음.
    front_camera.acquire()
    try:
        while True:
            # 평상시엔 공유 카메라 프레임, 추론 중엔 runner 릴레이 JPEG.
            jpeg = front_camera.latest_jpeg()
            if jpeg is None:
                await asyncio.sleep(0.05)
                continue
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(1 / 15)
    finally:
        front_camera.release()

@router.get("/camera/front/stream")
async def front_camera_stream(req: Request) -> StreamingResponse:
    """프론트 카메라 MJPEG 스트림 (RPS·추론 공용)."""
    async def gen():
        async for chunk in _mjpeg_gen():
            if await req.is_disconnected():
                break
            yield chunk
    return StreamingResponse(
        gen(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            # 웹(robot-web)이 COEP require-corp(cross-origin isolated) 라서
            # CORP 헤더 없으면 <img> 로드가 차단됨.
            "Cross-Origin-Resource-Policy": "cross-origin",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",  # 프록시 버퍼링 방지 (스트림 즉시 전달)
        },
    )


class AnswerRequest(BaseModel):
    answer: Literal["O", "X"] = Field(..., description="OX 퀴즈 정답")


def _bridge(req: Request) -> NoriarmRosBridge:
    bridge: NoriarmRosBridge | None = getattr(req.app.state, "noriarm_bridge", None)
    if bridge is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "noriarm bridge 가 초기화되지 않았습니다. ROS 환경 (source /opt/ros/jazzy/setup.bash) "
                "과 PYTHONPATH 에 noriarm_framework 가 있는지 확인."
            ),
        )
    return bridge


@router.get("/health")
async def health(req: Request) -> dict:
    """실물 NoriArm (OMX-F) 연결 여부 + bridge 활성 상태 (SR-NORI-006).

    실물 디바이스 검출은 `/dev/omx_follower` (udev 심볼릭 링크) 존재 여부 — 가벼운 1단계
    체크. 후속에서 dynamixel SDK ping 까지 추가 가능 (그때 timeout 처리 필요).

    응답 필드:
      - real_arm_present  : 실물 연결됐는지 (UI 가 URDF 뷰어 자동 표시 결정에 사용)
      - active_target     : 디폴트 권장 타깃 ("real" or "sim")
      - ros_available     : Control Server 가 ROS 환경에서 실행되는지 (bridge import 가능?)
      - bridge_running    : NoriarmRosBridge 가 실제로 활성화됐는지
    """
    real_present = False
    try:
        real_present = REAL_ARM_DEV.exists() and (
            REAL_ARM_DEV.is_char_device() or REAL_ARM_DEV.is_symlink()
        )
    except OSError:
        real_present = False

    bridge: NoriarmRosBridge | None = getattr(req.app.state, "noriarm_bridge", None)
    return {
        "real_arm_present": real_present,
        "real_dev_path": str(REAL_ARM_DEV),
        "active_target": "real" if real_present else "sim",
        "ros_available": ros_available(),
        "bridge_running": bridge is not None,
    }


@router.post("/games/ox-quiz/answer")
async def answer(req: Request, body: AnswerRequest) -> dict:
    bridge = _bridge(req)
    try:
        return await bridge.play_answer(body.answer)
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"trajectory 파일 못 찾음: {e}") from e


@router.get("/info")
async def info(req: Request) -> dict:
    bridge = _bridge(req)
    return bridge.info()


@router.get("/joint-states/stream")
async def joint_states_stream(req: Request) -> StreamingResponse:
    bridge = _bridge(req)
    return StreamingResponse(
        _joint_state_event_stream(req, bridge),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # 프록시가 버퍼링하지 않도록
            "Connection": "keep-alive",
        },
    )


# ---------- Vision (AI Hub proxy) ----------
# 실제 YOLO 추론은 AI Hub (service/ai-service/ai_service/hub.py) 가 담당. 여기는 brower → AI Hub 의
# 인증 게이트 + URL 매핑만. voice/intent / voice/tts 와 동일 패턴.

_VISION_TIMEOUT_S = 10.0


@router.get("/vision/tasks")
async def vision_tasks() -> dict:
    """AI Hub 의 등록된 vision task 목록을 그대로 forward."""
    try:
        async with httpx.AsyncClient(timeout=_VISION_TIMEOUT_S) as client:
            r = await client.get(f"{settings.ai_hub_url}/vision/tasks")
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"AI Hub unavailable: {exc}") from exc


@router.post("/vision/{task}/infer")
async def vision_infer(task: str, req: Request) -> dict:
    """1회성 추론 — AI Hub 의 동일 task endpoint 로 binary forward (디버깅용)."""
    body = await req.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty body")
    try:
        async with httpx.AsyncClient(timeout=_VISION_TIMEOUT_S) as client:
            r = await client.post(
                f"{settings.ai_hub_url}/vision/{task}/infer",
                content=body,
                headers={"Content-Type": "image/jpeg"},
            )
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"AI Hub unavailable: {exc}") from exc


def _ai_hub_ws_url(path: str) -> str:
    """settings.ai_hub_url (http://...) 를 ws:// 로 변환해 path 붙임."""
    parsed = urlparse(settings.ai_hub_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, path, "", "", ""))


@router.websocket("/vision/{task}/infer")
async def vision_infer_ws(ws: WebSocket, task: str) -> None:
    """브라우저 ↔ AI Hub WebSocket 프록시 (vision 스트리밍 추론).

    프로토콜:
      client → server : binary (image/jpeg)
      server → client : text (JSON)
    """
    await ws.accept()
    upstream_url = _ai_hub_ws_url(f"/vision/{task}/infer")
    try:
        async with websockets.connect(upstream_url, max_size=None) as upstream:
            async def to_upstream() -> None:
                while True:
                    data = await ws.receive_bytes()
                    await upstream.send(data)

            async def to_client() -> None:
                async for msg in upstream:
                    if isinstance(msg, bytes):
                        await ws.send_bytes(msg)
                    else:
                        await ws.send_text(msg)

            done, pending = await asyncio.wait(
                [asyncio.create_task(to_upstream()), asyncio.create_task(to_client())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("vision ws proxy 종료: %s", e)
        try:
            await ws.close(code=1011, reason=str(e)[:120])
        except Exception:
            pass


# ---------- /Vision ----------


async def _joint_state_event_stream(
    req: Request, bridge: NoriarmRosBridge
) -> AsyncIterator[str]:
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=120)

    def on_msg(payload: dict) -> None:
        # 큐가 차면 가장 오래된 것 버리고 새것 — 시각화용이라 lossy 허용.
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
                queue.put_nowait(payload)
            except Exception:
                pass

    unsubscribe = bridge.add_joint_state_listener(on_msg)
    logger.info("SSE client 접속 — joint-states/stream")
    try:
        # 즉시 ping 한 번 — 클라이언트가 connection 살아있음을 빨리 알도록.
        yield ": connected\n\n"
        while True:
            if await req.is_disconnected():
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                yield f"data: {json.dumps(payload)}\n\n"
            except asyncio.TimeoutError:
                # 메시지가 한참 없으면 keepalive 코멘트.
                yield ": keepalive\n\n"
    finally:
        unsubscribe()
        logger.info("SSE client 퇴장 — joint-states/stream")
