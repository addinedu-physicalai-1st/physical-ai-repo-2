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

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from server.control.noriarm.ros_bridge import NoriarmRosBridge, ros_available

# 실물 OMX-F follower 가 udev 룰로 만든 심볼릭 링크. 존재 여부로 연결 판정.
REAL_ARM_DEV = Path("/dev/omx_follower")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/noriarm", tags=["noriarm"])


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
