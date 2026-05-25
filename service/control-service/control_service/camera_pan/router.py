"""FastAPI router for camera pan/tilt teleop.

- POST /camera_pan/cmd : publish pan and/or tilt (at least one required).
- GET  /camera_pan/health
- WS   /camera_pan/state : 100ms snapshot broadcast.

No timeout watchdog (Arduino firmware + gogoping_camera_pan/servo_bridge node
handle setpoint persistence). PyQt 의존성 없음.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, model_validator

from control_service.camera_pan.ros_bridge import CameraPanBridge

WS_TICK_S = 0.1
QUEUE_MAX = 2


class CamCmdIn(BaseModel):
    pan: float | None = Field(default=None)
    tilt: float | None = Field(default=None)
    ts_ms: int | None = Field(default=None)

    @model_validator(mode="after")
    def _at_least_one_axis(self) -> "CamCmdIn":
        if self.pan is None and self.tilt is None:
            raise ValueError("pan 또는 tilt 중 최소 하나는 지정해야 합니다")
        return self


class _Hub:
    def __init__(self, bridge: CameraPanBridge) -> None:
        self._bridge = bridge
        self._clients: list[asyncio.Queue] = []
        self._tasks: list[asyncio.Task] = []
        self._stopped = False

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._tasks.append(loop.create_task(self._broadcaster()))

    async def stop(self) -> None:
        self._stopped = True
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()

    def _add_client(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        self._clients.append(q)
        return q

    def _remove_client(self, q: asyncio.Queue) -> None:
        try:
            self._clients.remove(q)
        except ValueError:
            pass

    async def _broadcaster(self) -> None:
        while not self._stopped:
            try:
                await asyncio.sleep(WS_TICK_S)
                snap = self._bridge.snapshot()
                payload = {
                    "ts_ms": int(time.time() * 1000),
                    "pan_deg": snap["pan_deg"],
                    "tilt_deg": snap["tilt_deg"],
                    "age_ms": snap["age_ms"],
                    "ros_ok": snap["ros_ok"],
                }
                for q in list(self._clients):
                    if q.full():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    try:
                        q.put_nowait(payload)
                    except asyncio.QueueFull:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception:
                continue


def make_router(
    bridge: CameraPanBridge, gogoping_bridge=None,
) -> tuple[APIRouter, _Hub]:
    router = APIRouter(prefix="/camera_pan", tags=["camera_pan"])
    hub = _Hub(bridge)

    @router.post("/cmd")
    async def post_cmd(payload: CamCmdIn) -> dict:
        try:
            if payload.pan is not None:
                bridge.publish_pan(payload.pan)
            if payload.tilt is not None:
                bridge.publish_tilt(payload.tilt)
        except Exception as exc:
            raise HTTPException(status_code=503, detail={
                "ok": False, "reason": f"ros_not_ready: {exc}",
            }) from exc
        if gogoping_bridge is not None:
            parts: list[str] = []
            if payload.pan is not None:
                parts.append(f"pan={payload.pan}")
            if payload.tilt is not None:
                parts.append(f"tilt={payload.tilt}")
            try:
                gogoping_bridge.publish_admin_event(
                    "camera_pan", " ".join(parts),
                )
            except Exception:
                pass
        return {"ok": True, "ts_ms": int(time.time() * 1000)}

    @router.get("/health")
    async def get_health() -> dict:
        return bridge.health()

    @router.websocket("/state")
    async def ws_state(ws: WebSocket) -> None:
        await ws.accept()
        q = hub._add_client()
        try:
            while True:
                payload = await q.get()
                await ws.send_json(payload)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            hub._remove_client(q)

    return router, hub


def install(
    app: FastAPI, bridge: CameraPanBridge, gogoping_bridge=None,
) -> _Hub:
    """app 에 camera_pan router 부착 + on_event 로 hub start/stop.

    main.py 가 lifespan= 을 지정한 app 에서는 on_event 가 무시되므로,
    main.py 측 lifespan 이 hub.start()/stop() 을 직접 호출한다.
    on_event 훅은 lifespan 없는 테스트용 FastAPI 인스턴스를 위해 남겨둠.

    gogoping_bridge: NavDebugLogCard 로 AdminUI 입력 publish (camera_pan 도 admin 입력).
    """
    router, hub = make_router(bridge, gogoping_bridge=gogoping_bridge)
    app.include_router(router)

    @app.on_event("startup")
    async def _hub_start() -> None:
        await hub.start()

    @app.on_event("shutdown")
    async def _hub_stop() -> None:
        await hub.stop()

    return hub
