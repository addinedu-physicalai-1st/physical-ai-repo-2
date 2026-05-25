"""FastAPI router for teleop endpoints.

- POST /teleop/cmd_vel: ros_bridge.publish_cmd_vel 호출.
- WS /teleop/state: 100ms 주기로 snapshot broadcast (asyncio.Queue maxsize=2).
- GET /teleop/health: ros_domain_id + age 정보.

이 모듈은 PyQt 관련 import 가 없어야 함 (AC #17).
asyncio 핸들러 안에서 rclpy.* 직접 호출 금지 — RosBridge 의 동기 메서드만 사용 (AC #23).
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Awaitable, Callable

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from control_service.teleop.ros_bridge import RosBridge

# 클라이언트 cmd_vel timeout — 마지막 수신 후 이 시간 안에 다음 수신 없으면 (0,0) 자동 발행
CMD_TIMEOUT_S = 0.5
# WS broadcast 주기 (s)
WS_TICK_S = 0.1
# scan ranges 다운샘플 길이 (AC #31)
RESAMPLE_N = 360
# WS 클라이언트 큐 크기 (AC #29)
QUEUE_MAX = 2


class CmdVelIn(BaseModel):
    linear: float = Field(...)
    angular: float = Field(...)
    ts_ms: int = Field(...)


def _resample(ranges: list[float], n: int = RESAMPLE_N) -> list[float]:
    """길이 임의의 ranges 를 n 개로 균일 다운샘플."""
    if not ranges:
        return []
    if len(ranges) == n:
        return list(ranges)
    out: list[float] = []
    step = len(ranges) / n
    for i in range(n):
        idx = int(i * step)
        if idx >= len(ranges):
            idx = len(ranges) - 1
        out.append(float(ranges[idx]))
    return out


class _Hub:
    """클라이언트별 asyncio.Queue 관리 + watchdog/broadcast task 보유.

    한 번의 라우터 인스턴스가 들고있는 단일 hub. 테스트는 mock bridge 로 수동 시작 가능.
    """

    def __init__(self, bridge: RosBridge) -> None:
        self._bridge = bridge
        self._clients: list[asyncio.Queue] = []
        self._tasks: list[asyncio.Task] = []
        self._extra_task_factory: Callable[[], Awaitable[None]] | None = None
        self._stopped = False

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._tasks.append(loop.create_task(self._watchdog()))
        self._tasks.append(loop.create_task(self._broadcaster()))
        if self._extra_task_factory is not None:
            self._tasks.append(loop.create_task(self._extra_task_factory()))

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

    async def _watchdog(self) -> None:
        """0.5 초 동안 cmd_vel 미수신 시 (0,0) 1 회 자동 발행 (AC #10).

        publish_cmd_vel 호출 후 _last_cmd_at_s 가 갱신되므로, watchdog 자신의 publish
        직후 age 가 0 으로 돌아가는 것을 새 클라이언트 명령으로 오인하지 않도록
        zeroed_at_age=None 트리거 플래그로 관리한다.
        """
        zero_armed = True  # 다음 timeout 시 publish 가능한가
        while not self._stopped:
            try:
                await asyncio.sleep(0.05)
                age = self._bridge.last_cmd_age_s()
                if age is None:
                    continue
                if age < CMD_TIMEOUT_S * 0.5:
                    # 진짜 새 cmd 가 들어옴 (반 시간 안에 갱신) → 다시 arm
                    zero_armed = True
                    continue
                if age >= CMD_TIMEOUT_S and zero_armed:
                    self._bridge.publish_cmd_vel(0.0, 0.0)
                    zero_armed = False
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

    async def _broadcaster(self) -> None:
        """WS_TICK_S 주기로 snapshot 을 모든 클라이언트 큐에 push.

        큐가 가득 차있으면 가장 오래된 메시지를 drop 한다 (AC #30).
        scan ranges 는 RESAMPLE_N 으로 다운샘플 후 송신 (AC #31).
        """
        while not self._stopped:
            try:
                await asyncio.sleep(WS_TICK_S)
                snap = self._bridge.snapshot()
                # spec §5.3: scan dict = {angle_min, angle_inc, ranges (resampled), hz, age_ms}
                scan_dict = None
                if snap["scan"] is not None:
                    scan_dict = {
                        "angle_min": snap["scan"]["angle_min"],
                        "angle_inc": snap["scan"]["angle_inc"],
                        "ranges": _resample(snap["scan"]["ranges"]),
                        "hz": snap["scan"].get("hz", 0.0),
                        "age_ms": snap["scan"].get("age_ms", 0),
                    }
                payload = {
                    "ts_ms": int(time.time() * 1000),
                    "odom": snap["odom"],
                    "scan": scan_dict,
                    "ros_ok": snap["ros_ok"],
                    "last_cmd_age_ms": snap["last_cmd_age_ms"],
                }
                for q in list(self._clients):
                    if q.full():
                        # 가장 오래된 메시지 drop
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


# teleop activity 1초 무명령 후 stop event — 별도 background task 가 폴링.
TELEOP_IDLE_S = 1.0
TELEOP_WATCH_TICK_S = 0.2


def make_router(
    bridge: RosBridge, gogoping_bridge=None,
) -> tuple[APIRouter, _Hub]:
    """teleop router + hub 페어 생성. 호출자가 lifespan 에서 hub.start()/stop() 관리.

    gogoping_bridge: AdminUI 입력 publisher (NavDebugLogCard 로 흐르는 cancel chain 옆
    에 ``teleop_start`` / ``teleop_stop`` 도 함께 보이게). None 이면 emit skip.
    """
    router = APIRouter(prefix="/teleop", tags=["teleop"])
    hub = _Hub(bridge)

    # teleop 활성 추적 — 첫 cmd_vel (1s idle 후) 에 start emit, 1s 무명령 시 stop emit.
    teleop_state = {"last_ts": 0.0, "active": False}

    def _maybe_emit_start() -> None:
        if gogoping_bridge is None:
            return
        now = time.time()
        last = teleop_state["last_ts"]
        if not teleop_state["active"] or (now - last) > TELEOP_IDLE_S:
            try:
                gogoping_bridge.publish_admin_event("teleop_start")
            except Exception:
                pass
            teleop_state["active"] = True
        teleop_state["last_ts"] = now

    @router.post("/cmd_vel")
    async def post_cmd_vel(payload: CmdVelIn) -> dict:
        # ros_bridge 의 동기 메서드만 호출 (AC #23: rclpy.* 직접 호출 X)
        try:
            bridge.publish_cmd_vel(payload.linear, payload.angular)
        except Exception as exc:
            raise HTTPException(status_code=503, detail={
                "ok": False, "reason": f"ros_not_ready: {exc}",
            }) from exc
        _maybe_emit_start()
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

    # teleop idle watcher — 1s 동안 cmd_vel 없으면 stop emit.
    async def _idle_watcher() -> None:
        try:
            while True:
                await asyncio.sleep(TELEOP_WATCH_TICK_S)
                if not teleop_state["active"]:
                    continue
                if (time.time() - teleop_state["last_ts"]) > TELEOP_IDLE_S:
                    teleop_state["active"] = False
                    if gogoping_bridge is not None:
                        try:
                            gogoping_bridge.publish_admin_event("teleop_stop")
                        except Exception:
                            pass
        except asyncio.CancelledError:
            return

    # background task — hub 가 시작될 때 함께 시작되도록 hub 에 부착.
    hub._extra_task_factory = _idle_watcher

    return router, hub


def install(app: FastAPI, bridge: RosBridge, gogoping_bridge=None) -> _Hub:
    """app 에 teleop router 부착 + lifespan hook 으로 hub start/stop.

    호출자: control_service.main 의 startup 단계에서 부른다.
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
