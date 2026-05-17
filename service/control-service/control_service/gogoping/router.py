"""GogoPing FSM/BT — REST + WS 엔드포인트.

- ``POST /api/gogoping/mode {robot: "gogoping", mode: "추종"}`` — 모드 클릭. mode_to_goal
  로 변환 후 SetGoal.srv 호출.
- ``WS /ws/robot-state`` — admin-app 이 구독. ros_bridge 의 /gogoping/state 받아 fan-out.

기존 ``/api/mode`` (control_service/main.py) 는 *로깅만* 하는 vestigial — 본 라우터로
대체될 때까지 호환.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .mode_to_goal import UnsupportedMode, mode_to_goal
from .ros_bridge import GogopingRosBridge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- Schemas


class GogopingModeRequest(BaseModel):
    """robot-web 이 mode 클릭 시 POST 하는 payload."""

    robot: str = Field(default="gogoping")
    mode: str  # 한국어 라벨 ("추종" / "운반" / "수동" / ...)


class GogopingModeResponse(BaseModel):
    accepted: bool
    reason: str = ""
    # 디버깅용 — 변환된 Goal 도 echo
    goal_mode: str = ""
    goal_task: str = ""


# ---------------------------------------------------------------- Router install


def install(app: FastAPI, bridge: GogopingRosBridge) -> None:
    """app 에 라우터 부착. ``bridge`` 는 lifespan 에서 미리 ``start()`` 호출되어 있어야 함."""

    router = APIRouter(prefix="/api/gogoping", tags=["gogoping"])

    @router.post("/mode", response_model=GogopingModeResponse)
    async def set_mode(req: GogopingModeRequest) -> GogopingModeResponse:
        if req.robot != "gogoping":
            raise HTTPException(400, f"unsupported robot: {req.robot!r}")
        try:
            goal = mode_to_goal(req.mode)
        except UnsupportedMode as e:
            raise HTTPException(400, str(e))

        # bridge 의 동기 호출 — asyncio thread 에서 호출하므로 to_thread 로 offload
        accepted, reason = await asyncio.to_thread(bridge.send_goal_sync, goal)
        if not accepted:
            logger.warning(
                f"SetGoal 거부: mode={req.mode!r} → Goal({goal.to_dict()}) "
                f"reason={reason!r}"
            )
        return GogopingModeResponse(
            accepted=accepted, reason=reason,
            goal_mode=goal.mode, goal_task=goal.task,
        )

    app.include_router(router)

    # WS /ws/robot-state — admin-app 이 구독
    _install_state_ws(app, bridge)


def _install_state_ws(app: FastAPI, bridge: GogopingRosBridge) -> None:
    """``/ws/robot-state`` WebSocket — bridge 의 /gogoping/state 메시지 fan-out."""

    @app.websocket("/ws/robot-state")
    async def robot_state_ws(ws: WebSocket) -> None:
        await ws.accept()
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=10)

        def _on_state(payload: dict) -> None:
            # ros_bridge spin thread 에서 호출 — asyncio queue 에 thread-safe put
            try:
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            except asyncio.QueueFull:
                pass  # 클라이언트가 느리면 drop — 1Hz 라 다음 메시지에서 갱신

        unreg = bridge.register_state_callback(_on_state)

        # 연결 즉시 latest state 한 번 (있으면) 보냄 — 새 클라이언트가 늦게 붙어도 즉시 표시
        latest = bridge.get_latest_state()
        if latest is not None:
            await ws.send_json(latest)

        try:
            while True:
                payload = await queue.get()
                await ws.send_json(payload)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning(f"robot-state WS 오류: {e}")
        finally:
            unreg()


__all__ = ["install", "GogopingModeRequest", "GogopingModeResponse"]
