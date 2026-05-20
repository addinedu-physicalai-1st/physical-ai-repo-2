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

from .mode_to_goal import Goal, UnsupportedMode, mode_to_goal
from .ros_bridge import GogopingRosBridge
from ..waypoints.ros_bridge import WaypointsRosBridge

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- Schemas


class GogopingModeRequest(BaseModel):
    """robot-web 이 mode 클릭 시 POST 하는 payload."""

    robot: str = Field(default="gogoping")
    mode: str  # 한국어 라벨 ("추종" / "이동" / "수동" / ...)


class GogopingModeResponse(BaseModel):
    accepted: bool
    reason: str = ""
    # 디버깅용 — 변환된 Goal 도 echo
    goal_mode: str = ""
    goal_task: str = ""


class GogopingGotoVertexRequest(BaseModel):
    """robot-web 음성 "X로 가" 처리. vertex 이름으로 ASSIST/goto 진입.

    `/waypoints/navigate` (graph_router action 직접) 와 달리 SetGoal.srv → FSM trigger 거침 — robot 이동 + state ASSIST 전이 둘 다 발생.
    """

    name: str  # waypoints.yaml 의 vertex 이름


class GogopingGotoVertexResponse(BaseModel):
    accepted: bool
    reason: str = ""
    destination_key: str = ""


# ---------------------------------------------------------------- Router install


_VALID_FORCE_STATES = (
    "CHARGING", "IDLE", "ASSIST", "PLAY", "MANUAL",
    "RETURNING", "LOW_BATTERY_RETURN", "ERROR",
)


class ForceStateRequest(BaseModel):
    """admin UI 의 디버그 패널이 POST 하는 payload."""
    target_state: str        # 8개 STATES 중 하나
    sub_task: str = ""       # 옵션 — "goto"/"follow"/"lullaby" (ASSIST) / "hideseek" (PLAY)


class ForceStateResponse(BaseModel):
    accepted: bool
    reason: str = ""
    current_state: str = ""  # bridge 가 최근 본 state (참고용)


class BatteryDebugRequest(BaseModel):
    """admin UI 의 BatteryDebugSlider 가 POST 하는 payload."""
    level: float = Field(ge=0.0, le=100.0)


class BatteryDebugResponse(BaseModel):
    accepted: bool
    reason: str = ""


class RobotPoseDebugRequest(BaseModel):
    """admin UI 의 MapStatusCard 디버그가 POST 하는 payload.

    clear=True 면 x/y/yaw 무시, override 해제. clear=False 면 좌표 강제.
    """
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    clear: bool = False


class RobotPoseDebugResponse(BaseModel):
    accepted: bool
    reason: str = ""
    # 가제보 텔레포트 결과 (sim 만 동작, 실물 service_unavailable)
    gazebo_accepted: bool = False
    gazebo_reason: str = ""
    # AMCL /initialpose publish 결과 — RViz/AMCL 위치 추정 재초기화
    amcl_published: bool = False


class EmergencyStopResponse(BaseModel):
    accepted: bool
    reason: str = ""


def install(
    app: FastAPI,
    bridge: GogopingRosBridge,
    waypoints_bridge: WaypointsRosBridge,
) -> None:
    """app 에 라우터 부착. ``bridge`` / ``waypoints_bridge`` 는 lifespan 에서 미리
    ``start()`` 호출되어 있어야 함.

    ``waypoints_bridge`` 는 ``/debug/pose`` 가 AMCL ``/initialpose`` 도 같이 publish
    하기 위해 필요 (RViz 와 Gazebo 동시 이동 — Step 1)."""

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

    @router.post("/goto_vertex", response_model=GogopingGotoVertexResponse)
    async def goto_vertex(req: GogopingGotoVertexRequest) -> GogopingGotoVertexResponse:
        goal = Goal(mode="ASSIST", task="goto", destination_key=req.name)
        accepted, reason = await asyncio.to_thread(bridge.send_goal_sync, goal)
        if not accepted:
            logger.warning(
                f"SetGoal 거부 (goto_vertex): name={req.name!r} reason={reason!r}"
            )
        return GogopingGotoVertexResponse(
            accepted=accepted, reason=reason, destination_key=req.name,
        )

    @router.post("/debug/force-state", response_model=ForceStateResponse)
    async def force_state(req: ForceStateRequest) -> ForceStateResponse:
        """[디버그 전용] FSM 강제 state 전이 (+ 옵션 sub_task)."""
        if req.target_state not in _VALID_FORCE_STATES:
            raise HTTPException(400, f"invalid target_state: {req.target_state!r}")
        accepted, reason = await asyncio.to_thread(
            bridge.force_state_sync, req.target_state, req.sub_task,
        )
        latest = bridge.get_latest_state() or {}
        return ForceStateResponse(
            accepted=accepted, reason=reason,
            current_state=latest.get("fsm_state", ""),
        )

    @router.post("/debug/battery", response_model=BatteryDebugResponse)
    async def set_battery(req: BatteryDebugRequest) -> BatteryDebugResponse:
        """[sim 디버그 전용] 배터리 레벨 강제 설정 — sim_battery_node 서버.

        운영(실물 Pi) 환경엔 server 없음 → ``service_unavailable`` 반환.
        """
        accepted, reason = await asyncio.to_thread(
            bridge.set_battery_level_sync, req.level,
        )
        if not accepted:
            logger.warning(
                f"SetBatteryLevel 거부: level={req.level} reason={reason!r}"
            )
        return BatteryDebugResponse(accepted=accepted, reason=reason)

    @router.post("/debug/pose", response_model=RobotPoseDebugResponse)
    async def set_robot_pose(req: RobotPoseDebugRequest) -> RobotPoseDebugResponse:
        """[디버그] 로봇 좌표 강제 — SW override + gazebo 텔레포트 + AMCL /initialpose 동시.

        - SW override (SetRobotPose.srv): sim + 실물 둘 다 동작. blackboard.ROBOT_POSE
          강제 + POSE_OVERRIDE_ACTIVE flag → PoseSubscriber 가 amcl_pose 무시.
        - 가제보 텔레포트 (SetGazeboPose.srv): sim 만. gz set_pose service 호출.
          실물엔 sim_teleport_node 없음 → service_unavailable (best-effort, 무시).
        - AMCL /initialpose publish: RViz 의 robot frame 도 같은 위치로 이동
          (waypoints_bridge.set_initial_pose 재사용). sim/실물 동일 동작.

        clear=True 면 SW override 만 해제 (가제보 텔레포트 + /initialpose skip).
        """
        accepted, reason = await asyncio.to_thread(
            bridge.set_robot_pose_sync, req.x, req.y, req.yaw, req.clear,
        )
        if not accepted:
            logger.warning(
                f"SetRobotPose 거부: x={req.x} y={req.y} yaw={req.yaw} "
                f"clear={req.clear} reason={reason!r}"
            )

        # clear=True 면 가제보 텔레포트 + /initialpose skip — 그냥 live amcl_pose 복원만
        gz_ok = False
        gz_reason = "skipped_on_clear"
        amcl_published = False
        if not req.clear:
            gz_ok, gz_reason = await asyncio.to_thread(
                bridge.set_gazebo_pose_sync, req.x, req.y, req.yaw,
            )
            if not gz_ok:
                # sim_teleport_node 없는 실물 환경에선 service_unavailable — 정상
                logger.info(
                    f"SetGazeboPose (sim 전용) 응답: ok={gz_ok} reason={gz_reason!r}"
                )

            # AMCL /initialpose publish — sim/실물 동일. 실패해도 SetRobotPose override 가
            # 이미 BB.ROBOT_POSE 를 잡고 있으므로 best-effort.
            try:
                await asyncio.to_thread(
                    waypoints_bridge.set_initial_pose, req.x, req.y, req.yaw,
                )
                amcl_published = True
            except Exception as e:
                logger.warning(f"/initialpose publish 실패: {e!r}")

        return RobotPoseDebugResponse(
            accepted=accepted, reason=reason,
            gazebo_accepted=gz_ok, gazebo_reason=gz_reason,
            amcl_published=amcl_published,
        )

    @router.post("/emergency_stop", response_model=EmergencyStopResponse)
    async def emergency_stop() -> EmergencyStopResponse:
        """긴급정지 — Admin UI / 외부 안전 시스템 호출.

        ``/gogoping/emergency_stop`` (std_srvs/Trigger) 로 gogoping_modes 의 FSM 을
        ERROR (terminal) 로 강제 전이. BT_error_main 의 StopAllMotors 가 cmd_vel=0 +
        torque OFF 실행. ERROR 는 사용자가 robot 재시작해야 복구 가능.
        """
        accepted, reason = await asyncio.to_thread(bridge.emergency_stop_sync)
        if not accepted:
            logger.warning(f"EmergencyStop 거부: reason={reason!r}")
        return EmergencyStopResponse(accepted=accepted, reason=reason)

    app.include_router(router)

    # WS /ws/robot-state — admin-app 이 구독
    _install_state_ws(app, bridge)
    # WS /ws/nav-debug-events — admin-app 의 NavDebugLogCard 가 구독
    _install_nav_event_ws(app, bridge)


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


def _install_nav_event_ws(app: FastAPI, bridge: GogopingRosBridge) -> None:
    """``/ws/nav-debug-events`` WebSocket — bridge 의 /gogoping/debug/nav_events fan-out.

    연결 즉시 ``get_recent_nav_events()`` backfill (최근 200개) 한 번 보내고, 이후
    spin thread 에서 callback 으로 push.
    """

    @app.websocket("/ws/nav-debug-events")
    async def nav_event_ws(ws: WebSocket) -> None:
        await ws.accept()
        loop = asyncio.get_event_loop()
        # depth 깊게 — burst (cancel chain 한 cycle = 9~10 event 가 ~1초 안에) 안 잃게
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=200)

        def _on_event(payload: dict) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            except asyncio.QueueFull:
                # 클라이언트가 너무 느리면 drop — admin UI 는 어차피 최근만 표시
                pass

        unreg = bridge.register_nav_event_callback(_on_event)

        # backfill
        for payload in bridge.get_recent_nav_events():
            try:
                await ws.send_json(payload)
            except Exception:
                break

        try:
            while True:
                payload = await queue.get()
                await ws.send_json(payload)
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning(f"nav-debug-events WS 오류: {e}")
        finally:
            unreg()


__all__ = [
    "install",
    "GogopingModeRequest", "GogopingModeResponse",
    "ForceStateRequest", "ForceStateResponse",
    "BatteryDebugRequest", "BatteryDebugResponse",
    "RobotPoseDebugRequest", "RobotPoseDebugResponse",
    "EmergencyStopResponse",
]
