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
import random
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from .state_to_goal import Goal, UnsupportedMode, mode_to_goal
from .ros_bridge import GogopingRosBridge
from ..waypoints import yaml_store
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
    goal_target_state: str = ""


class GogopingGotoVertexRequest(BaseModel):
    """robot-web 음성 "X로 가" 처리. vertex 이름으로 GOTO 진입.

    `/waypoints/navigate` (graph_router action 직접) 와 달리 SetGoal.srv → FSM trigger 거침 — robot 이동 + state GOTO 전이 둘 다 발생.

    then_mode: 복합 명령 "X 가서 Y" — 도착(GOTO→IDLE) 후 전환할 모드. 정보불필요
    모드(자장가/수동/대기)만. 빈 문자열이면 단순 이동. 서버가 background task 로
    도착 감지 후 모드 전환 (robot-web 은 state 스트림이 없어 서버가 orchestrate).
    """

    name: str  # waypoints.yaml 의 vertex 이름
    then_mode: str = ""


class GogopingGotoVertexResponse(BaseModel):
    accepted: bool
    reason: str = ""
    destination_key: str = ""


# ---------------------------------------------------------------- Router install


_VALID_FORCE_STATES = (
    "IDLE", "CHARGING", "GOTO", "FOLLOW", "LULLABY", "HIDEANDSEEK",
    "MANUAL", "RETURNING", "LOW_BATTERY_RETURNING", "ERROR",
)


class ForceStateRequest(BaseModel):
    """admin UI 의 디버그 패널이 POST 하는 payload."""
    target_state: str        # 10개 STATES 중 하나 (평탄화 후 sub_task 제거)


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


class IdleTimeoutRequest(BaseModel):
    """IDLE → RETURNING 자동 복귀 임계값 변경.

    seconds: 1.0 ~ 86400.0 (1초 ~ 24시간). gogoping_modes 노드의 ROS param
    ``idle_timeout_seconds`` 를 변경하고 IdleTimeoutMonitor 가 즉시 반영.
    """
    seconds: float


class IdleTimeoutResponse(BaseModel):
    accepted: bool
    reason: str = ""
    seconds: float = 0.0


class HideseekRecruitCompleteRequest(BaseModel):
    """robot-web RecruitPhase '출발' 버튼이 POST.

    child_ids: 모집된 아이들의 DB child_id 리스트 (빈 리스트도 허용 — UI 측이 검증).
    """
    child_ids: list[int]


class HideseekRecruitCompleteResponse(BaseModel):
    accepted: bool
    reason: str = ""
    count: int = 0


class HideseekCaughtRequest(BaseModel):
    """robot-web PatrolPhase/ReturnPhase 인식 파이프라인이 POST.

    child_id: 발견된 아이의 DB child_id.
    caught_at_waypoint: 발견 시 vertex 이름 (UI 표시용 — BT 는 사용 안 함).
    """
    child_id: int
    caught_at_waypoint: str | None = None


class HideseekCaughtResponse(BaseModel):
    accepted: bool
    reason: str = ""
    child_id: int = 0


class HideseekSkipPhaseRequest(BaseModel):
    """robot-web 의 debug "다음 단계" 버튼이 POST.

    current_phase: 현재 UI 가 표시 중인 phase 이름.
        - "recruit"   → registered_ids=[1] (dummy) → AwaitRecruitComplete SUCCESS
        - "countdown" → skip_countdown=True → BT Countdown 즉시 SUCCESS
        - "patrol"    → caught_ids = sentinel large set → CaughtMonitor SUCCESS
        - "return"    → 동일 (caught_ids sentinel)
        - "move_to_play" / "end" → 지원 안 함 (BT goto/유휴 영구 RUNNING — UI 가 cancel 로 처리)
    """
    current_phase: str


class HideseekSkipPhaseResponse(BaseModel):
    accepted: bool
    reason: str = ""
    advanced_to: str = ""   # next phase 이름 (UI 표시용)


class PatrolRequest(BaseModel):
    """admin UI [순찰] 버튼이 POST 하는 payload — 현재 옵션 없음.

    모든 group 카테고리를 랜덤 순서로 순회 (그룹 내는 robot 위치 NN 정렬).
    """
    pass


class PatrolResponse(BaseModel):
    accepted: bool
    reason: str = ""
    # 셔플된 그룹 순서 (echo)
    group_order: list[str] = []
    # 정렬된 vertex 리스트 (echo, 그룹 순서 + 그룹 내 NN)
    vertices: list[str] = []
    # 사용된 시작 좌표 — robot pose 못 받으면 첫 vertex 의 좌표
    start_x: float = 0.0
    start_y: float = 0.0
    used_robot_pose: bool = False


def _build_group_patrol_order(
    bridge: GogopingRosBridge,
) -> tuple[list[str], list[str], tuple[float, float] | None]:
    """waypoints.yaml 의 group 별 모든 vertex 를 셔플된 group 순서 + group 내 NN
    으로 정렬해 단일 list 로 반환. ``/debug/patrol`` 과 동일 로직 — 숨바꼭질 모드
    진입 시에도 같은 patrol 계획을 쓴다.

    반환:
        (ordered, group_order, start_pose)
            ordered: 모든 group 의 vertex 가 셔플된 순서로 펼쳐진 list
            group_order: 셔플된 group 이름 list (UI 의 "N 카테고리" 표시용)
            start_pose: NN 시작 좌표 (robot pose 가 있으면 그 값, 없으면 None)

    grouped vertex 가 하나도 없으면 (빈, 빈, None) 반환.
    """
    wps, _ = yaml_store.load()
    groups: dict[str, list[tuple[str, float, float]]] = {}
    for w in wps:
        if w.group:
            groups.setdefault(w.group, []).append(
                (w.name, float(w.x), float(w.y))
            )
    if not groups:
        return [], [], None

    group_order = list(groups.keys())
    random.shuffle(group_order)

    latest = bridge.get_latest_state() or {}
    pose = latest.get("robot_pose") if isinstance(latest, dict) else None
    if (isinstance(pose, dict)
            and isinstance(pose.get("x"), (int, float))
            and isinstance(pose.get("y"), (int, float))):
        cur_x, cur_y = float(pose["x"]), float(pose["y"])
        start_pose: tuple[float, float] | None = (cur_x, cur_y)
    else:
        first_grp = groups[group_order[0]]
        cur_x, cur_y = first_grp[0][1], first_grp[0][2]
        start_pose = None

    ordered: list[str] = []
    for grp_name in group_order:
        remaining = list(groups[grp_name])
        while remaining:
            best = min(
                remaining,
                key=lambda w: (w[1] - cur_x) ** 2 + (w[2] - cur_y) ** 2,
            )
            ordered.append(best[0])
            cur_x, cur_y = best[1], best[2]
            remaining.remove(best)

    return ordered, group_order, start_pose


def _build_hideseek_goal_dynamic(bridge: GogopingRosBridge, base: Goal) -> Goal:
    """``숨바꼭질`` 진입 시 search_waypoints 를 group 셔플 + NN 정렬로 채운다.

    `/debug/patrol` 과 동일 로직 (``_build_group_patrol_order``). 모든 grouped
    vertex 를 한 번씩 순회 — group 수 = 사용자가 보는 카테고리 수.

    play_area_key 는 base.play_area_key (state_to_goal 의 "복도") 그대로 유지 —
    모집/카운트다운/복귀 도착점.

    yaml 에 grouped vertex 가 없으면 base 의 hardcoded search_waypoints 그대로
    반환 (degenerate fallback).
    """
    try:
        ordered, group_order, _ = _build_group_patrol_order(bridge)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"_build_group_patrol_order 실패 — hideseek fallback: {e}")
        return base

    if not ordered:
        logger.warning("waypoints.yaml 에 grouped vertex 없음 — hideseek fallback")
        return base

    logger.info(
        f"hideseek dynamic patrol: {len(group_order)} categories "
        f"({group_order}) → {len(ordered)} vertices in NN order"
    )
    return Goal(
        target_state=base.target_state,
        destination_key=base.destination_key,
        target_id=base.target_id,
        search_waypoints=ordered,
        play_area_key=base.play_area_key,
    )


# 복합 명령 "X 가서 Y" 에서 도착 후 전환 허용할 모드 — 정보불필요(추가 대상/장소 X) 만.
# 이동/추종/숨바꼭질은 목적지/대상이 필요해 체인 대상에서 제외 (state_to_goal 의 demo 기본값 회피).
_CHAINABLE_THEN_MODES = frozenset({"자장가", "수동", "대기"})

# 도착 감지 polling — 0.5s 간격. 도착(이동 중) 대기엔 타임아웃 없음 (사용자 요청).
# 단 GOTO 가 시작조차 안 하면(then_mode 는 왔는데 goto 전이 실패 등) 좀비 방지로
# _STARTUP_GRACE_POLLS(=60s) 안에 GOTO 를 못 보면 포기.
_ARRIVAL_POLL_INTERVAL_S = 0.5
_STARTUP_GRACE_POLLS = 120  # 60s — GOTO 시작 관측 유예

# 진행 중인 goto→then_mode 체인 task. 새 명령(goto/mode)이 들어오면 취소 → 새 명령 우선.
# 단일 로봇 가정 — 동시에 하나의 체인만 유효.
_pending_chain_task: "asyncio.Task | None" = None


def _cancel_pending_chain(reason: str) -> None:
    """진행 중인 goto→then_mode 체인을 취소 — 새 명령이 우선하도록.

    goto_vertex / set_mode 등 새 명령 진입 시 호출. 취소되면 도착 후 then_mode 전환이
    발생하지 않음 (예: '수면실 가서 자장가' 중 '복귀'/'정지'/'추종' 들어오면 자장가 skip).
    """
    global _pending_chain_task
    t = _pending_chain_task
    _pending_chain_task = None
    if t is not None and not t.done():
        t.cancel()
        logger.info(f"[goto_then_mode] 진행 중 체인 취소 — {reason}")


async def _await_arrival_then_mode(
    bridge: GogopingRosBridge, name: str, then_mode: str
) -> None:
    """GOTO 도착(GOTO→IDLE) 감지 후 then_mode 로 전환 — server orchestration.

    robot-web 은 FSM state 스트림이 없어 control-service 가 ``get_latest_state()`` 로
    polling. GOTO 를 한 번 본 뒤 IDLE 로 돌아오면 도착으로 간주 → mode_to_goal(then_mode)
    전송. GOTO/IDLE 외 다른 state(error/다른 task)로 가면 체인 취소. 새 명령(goto/mode)이
    오면 ``_cancel_pending_chain`` 으로 외부 취소됨. 도착 대기엔 타임아웃 없음 — 단 GOTO
    시작 자체를 _STARTUP_GRACE_POLLS 안에 못 보면 포기(좀비 방지).
    """
    global _pending_chain_task
    logger.info(f"[goto_then_mode] watcher 시작 target={name!r} then_mode={then_mode!r}")
    try:
        seen_goto = False
        startup_polls = 0
        while True:
            await asyncio.sleep(_ARRIVAL_POLL_INTERVAL_S)
            st = bridge.get_latest_state() or {}
            fsm = st.get("fsm_state", "")
            if fsm == "GOTO":
                if not seen_goto:
                    logger.info("[goto_then_mode] GOTO 감지 — 도착 대기 (타임아웃 없음)")
                seen_goto = True
                continue
            if not seen_goto:
                # 아직 GOTO 진입 전 — startup grace 안에서만 대기.
                startup_polls += 1
                if startup_polls >= _STARTUP_GRACE_POLLS:
                    logger.warning(
                        f"[goto_then_mode] GOTO 시작 못 봄 ({_STARTUP_GRACE_POLLS*_ARRIVAL_POLL_INTERVAL_S:.0f}s) — 포기 {name!r}"
                    )
                    bridge.publish_admin_event(
                        "goto_then_mode", f"never entered GOTO {name!r}→{then_mode!r}",
                    )
                    return
                continue
            if fsm == "IDLE":
                # 도착 — then_mode 전환.
                logger.info(f"[goto_then_mode] 도착(IDLE) 감지 → {then_mode!r} 전환")
                try:
                    goal = mode_to_goal(then_mode)
                except UnsupportedMode as e:
                    logger.warning(f"goto_then_mode: bad then_mode={then_mode!r}: {e}")
                    return
                accepted, reason = await asyncio.to_thread(bridge.send_goal_sync, goal)
                logger.info(
                    f"[goto_then_mode] {then_mode!r} 전환 결과 accepted={accepted} reason={reason!r}"
                )
                bridge.publish_admin_event(
                    "goto_then_mode",
                    f"arrived {name!r} → {then_mode!r} accepted={accepted} reason={reason!r}",
                )
                return
            # GOTO/IDLE 외 다른 state — 체인 취소 (error / 다른 task 가 직접 전이).
            logger.info(f"[goto_then_mode] 체인 중단 — 예상밖 state={fsm!r}")
            bridge.publish_admin_event(
                "goto_then_mode", f"chain aborted (state={fsm!r}) {name!r}→{then_mode!r}",
            )
            return
    except asyncio.CancelledError:
        logger.info(f"[goto_then_mode] 체인 취소됨 (새 명령 우선) {name!r}→{then_mode!r}")
        raise
    finally:
        # 자기 자신이 현재 pending 이면 clear (외부에서 이미 교체했으면 건드리지 않음).
        if _pending_chain_task is asyncio.current_task():
            _pending_chain_task = None


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
        # 새 모드 명령 — 진행 중인 goto→then_mode 체인이 있으면 취소 (새 명령 우선).
        # 예: '수면실 가서 자장가' 중 '복귀'/'정지'/'추종' 들어오면 자장가 전환 안 함.
        _cancel_pending_chain(f"new mode {req.mode!r}")
        bridge.publish_admin_event("mode", f"mode={req.mode!r}")
        try:
            goal = mode_to_goal(req.mode)
        except UnsupportedMode as e:
            raise HTTPException(400, str(e))

        # HIDEANDSEEK 진입 — robot UI [숨바꼭질] 메뉴. 6-step Sequence 전체.
        # search_waypoints 는 group 셔플 + NN 으로 동적 채움.
        # patrol_only flag 는 명시 False — 이전 admin [순찰] 호출 잔여 cleanup.
        if goal.target_state == "HIDEANDSEEK":
            goal = await asyncio.to_thread(
                _build_hideseek_goal_dynamic, bridge, goal,
            )
            await asyncio.to_thread(bridge.write_hideseek_patrol_only, False)

        # bridge 의 동기 호출 — asyncio thread 에서 호출하므로 to_thread 로 offload
        accepted, reason = await asyncio.to_thread(bridge.send_goal_sync, goal)
        if not accepted:
            logger.warning(
                f"SetGoal 거부: mode={req.mode!r} → Goal({goal.to_dict()}) "
                f"reason={reason!r}"
            )
        return GogopingModeResponse(
            accepted=accepted, reason=reason,
            goal_target_state=goal.target_state,
        )

    @router.post("/goto_vertex", response_model=GogopingGotoVertexResponse)
    async def goto_vertex(req: GogopingGotoVertexRequest) -> GogopingGotoVertexResponse:
        global _pending_chain_task
        logger.info(
            f"[goto_vertex] name={req.name!r} then_mode={req.then_mode!r}"
        )
        # 새 이동 명령 — 이전 goto→then_mode 체인이 진행 중이면 취소 (새 명령 우선).
        _cancel_pending_chain(f"new goto_vertex {req.name!r}")
        bridge.publish_admin_event(
            "goto_vertex", f"name={req.name!r} then_mode={req.then_mode!r}"
        )
        goal = Goal(target_state="GOTO", destination_key=req.name)
        accepted, reason = await asyncio.to_thread(bridge.send_goal_sync, goal)
        if not accepted:
            logger.warning(
                f"SetGoal 거부 (goto_vertex): name={req.name!r} reason={reason!r}"
            )
        # 복합 명령 "X 가서 Y" — GOTO 수락됐고 then_mode 가 chainable 이면
        # 도착(GOTO→IDLE) 후 모드 전환을 background task 로 orchestrate.
        if accepted and req.then_mode in _CHAINABLE_THEN_MODES:
            logger.info(
                f"[goto_vertex] then_mode={req.then_mode!r} chainable → "
                f"arrival watcher 시작 (target={req.name!r})"
            )
            _pending_chain_task = asyncio.create_task(
                _await_arrival_then_mode(bridge, req.name, req.then_mode)
            )
        elif req.then_mode:
            logger.warning(
                f"[goto_vertex] then_mode={req.then_mode!r} 는 chainable 아님 "
                f"(허용: {sorted(_CHAINABLE_THEN_MODES)}) — 체인 skip"
            )
        return GogopingGotoVertexResponse(
            accepted=accepted, reason=reason, destination_key=req.name,
        )

    @router.post("/debug/force-state", response_model=ForceStateResponse)
    async def force_state(req: ForceStateRequest) -> ForceStateResponse:
        """[디버그 전용] FSM 강제 state 전이.

        평탄화 (2026-05-25): sub_task 필드 제거. 10개 state 중 하나로 직접 진입.
        """
        if req.target_state not in _VALID_FORCE_STATES:
            raise HTTPException(400, f"invalid target_state: {req.target_state!r}")
        bridge.publish_admin_event("force_state", f"target={req.target_state!r}")
        accepted, reason = await asyncio.to_thread(
            bridge.force_state_sync, req.target_state,
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
        bridge.publish_admin_event("set_battery", f"level={req.level}")
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
        if req.clear:
            bridge.publish_admin_event("set_pose", "clear=True")
        else:
            bridge.publish_admin_event(
                "set_pose", f"x={req.x:.2f} y={req.y:.2f} yaw={req.yaw:.2f}"
            )
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

    @router.post("/debug/patrol", response_model=PatrolResponse)
    async def trigger_patrol(req: PatrolRequest) -> PatrolResponse:
        """[디버그] 모든 그룹을 랜덤 순서로 순회 — 그룹 내는 robot 위치 NN 정렬.

        - waypoints.yaml 의 ``group`` 채워진 vertex 만 후보 (group=None 제외)
        - 그룹 리스트 ``random.shuffle`` → 그 순서대로 순회
        - 첫 그룹: ``/gogoping/state`` 의 ``robot_pose`` 에서 NN 시작 (없으면 그룹 첫 vertex)
        - 다음 그룹들: 이전 그룹의 마지막 vertex 좌표에서 NN 시작
        - 결과: 모든 group vertex 가 하나의 search_waypoints 리스트에 들어감
        """
        bridge.publish_admin_event("patrol_start")
        ordered, group_order, start_pose = await asyncio.to_thread(
            _build_group_patrol_order, bridge,
        )
        if not ordered:
            return PatrolResponse(accepted=False, reason="no_grouped_vertices")

        if start_pose is not None:
            start_x, start_y = start_pose
            used_robot_pose = True
        else:
            # fallback: ordered 의 첫 vertex 좌표 (yaml lookup 필요한데 한 번 더 load
            # 하긴 비효율 — 0,0 으로 둠. 디버그 응답 metadata 라 정확도 덜 중요)
            start_x, start_y = 0.0, 0.0
            used_robot_pose = False

        goal = Goal(
            target_state="HIDEANDSEEK",
            target_id="patrol_debug",
            search_waypoints=ordered,
            # reconciler 가 HIDEANDSEEK 진입 시 필수 필드 (missing_play_area_key 방지).
            # /debug/patrol 은 nav 검증용 — 복도 default 로 충분.
            play_area_key="복도",
        )
        # patrol_only=True 셋 — SetGoal 보다 먼저 셋팅해야 BT builder 가 정확히 읽음.
        # builder 가 이 flag 보면 6-step 전체 대신 SetHideseekPhase("patrol") + patrol_sub 만 반환.
        await asyncio.to_thread(bridge.write_hideseek_patrol_only, True)
        accepted, reason = await asyncio.to_thread(bridge.send_goal_sync, goal)
        if not accepted:
            logger.warning(
                f"Patrol SetGoal 거부: group_order={group_order!r} "
                f"vertices={ordered!r} reason={reason!r}"
            )
        return PatrolResponse(
            accepted=accepted, reason=reason,
            group_order=group_order,
            vertices=ordered,
            start_x=start_x, start_y=start_y,
            used_robot_pose=used_robot_pose,
        )

    @router.post(
        "/play/hideseek/recruit-complete",
        response_model=HideseekRecruitCompleteResponse,
    )
    async def hideseek_recruit_complete(
        req: HideseekRecruitCompleteRequest,
    ) -> HideseekRecruitCompleteResponse:
        """robot-web RecruitPhase '출발' 버튼 — 모집된 child_ids 를 BT 에 전달.

        ``bridge.write_hideseek_registered_ids(ids)`` 가 ``SetBlackboard.srv`` 로
        ``hideseek_registered_ids`` 키를 셋팅. BT 의 AwaitRecruitComplete 가 polling →
        SUCCESS → CountDown 단계로 진입.

        부수효과: caught_ids 누적 캐시 reset (새 round 시작).
        """
        accepted, reason = await asyncio.to_thread(
            bridge.write_hideseek_registered_ids, list(req.child_ids),
        )
        if not accepted:
            logger.warning(
                f"HideseekRecruitComplete 거부: child_ids={req.child_ids!r} "
                f"reason={reason!r}"
            )
        return HideseekRecruitCompleteResponse(
            accepted=accepted, reason=reason, count=len(req.child_ids),
        )

    @router.post(
        "/play/hideseek/caught", response_model=HideseekCaughtResponse,
    )
    async def hideseek_caught(
        req: HideseekCaughtRequest,
    ) -> HideseekCaughtResponse:
        """robot-web PatrolPhase/ReturnPhase 인식 — 발견한 child_id 누적.

        ``bridge.append_hideseek_caught_id(child_id)`` 가 in-process 누적 set 에
        추가 후 ``SetBlackboard.srv`` 로 sorted list 전체를 셋팅. BT 의
        HideSeekCaughtMonitor 가 registered ⊆ caught 검사 → 모두 잡힘 시 SUCCESS.

        같은 child_id 중복 호출 무해. ``caught_at_waypoint`` 는 로깅용
        (BT 는 사용 안 함).
        """
        accepted, reason = await asyncio.to_thread(
            bridge.append_hideseek_caught_id, int(req.child_id),
        )
        if not accepted:
            logger.warning(
                f"HideseekCaught 거부: child_id={req.child_id} "
                f"caught_at_waypoint={req.caught_at_waypoint!r} reason={reason!r}"
            )
        return HideseekCaughtResponse(
            accepted=accepted, reason=reason, child_id=req.child_id,
        )

    @router.post(
        "/play/hideseek/debug/skip-phase",
        response_model=HideseekSkipPhaseResponse,
    )
    async def hideseek_skip_phase(
        req: HideseekSkipPhaseRequest,
    ) -> HideseekSkipPhaseResponse:
        """robot-web 의 debug "다음 단계" 버튼 — 현재 phase 를 SUCCESS 시켜 다음으로.

        지원 phase: recruit / countdown / patrol / return.
        move_to_play / end 는 BT goto / 영구 RUNNING 이라 skip 효과 없음 (UI 가
        cancel 로 처리하거나 무시).
        """
        phase = req.current_phase
        if phase == "recruit":
            accepted, reason = await asyncio.to_thread(
                bridge.write_hideseek_registered_ids, [1],
            )
            return HideseekSkipPhaseResponse(
                accepted=accepted, reason=reason, advanced_to="countdown",
            )
        if phase == "countdown":
            accepted, reason = await asyncio.to_thread(
                bridge.write_hideseek_skip_countdown, True,
            )
            return HideseekSkipPhaseResponse(
                accepted=accepted, reason=reason, advanced_to="patrol",
            )
        if phase in ("patrol", "return"):
            accepted, reason = await asyncio.to_thread(
                bridge.write_hideseek_caught_ids_complete,
            )
            return HideseekSkipPhaseResponse(
                accepted=accepted, reason=reason,
                advanced_to="return" if phase == "patrol" else "end",
            )
        return HideseekSkipPhaseResponse(
            accepted=False,
            reason=f"phase_not_skippable: {phase!r}",
            advanced_to="",
        )

    @router.post("/emergency_stop", response_model=EmergencyStopResponse)
    async def emergency_stop() -> EmergencyStopResponse:
        """긴급정지 — Admin UI / 외부 안전 시스템 호출.

        ``/gogoping/emergency_stop`` (std_srvs/Trigger) 로 gogoping_modes 의 FSM 을
        ERROR (terminal) 로 강제 전이. BT_error_main 의 StopAllMotors 가 cmd_vel=0 +
        torque OFF 실행. ERROR 는 사용자가 robot 재시작해야 복구 가능.
        """
        bridge.publish_admin_event("estop", level="warn")
        accepted, reason = await asyncio.to_thread(bridge.emergency_stop_sync)
        if not accepted:
            logger.warning(f"EmergencyStop 거부: reason={reason!r}")
        return EmergencyStopResponse(accepted=accepted, reason=reason)

    @router.post("/idle_timeout", response_model=IdleTimeoutResponse)
    async def set_idle_timeout(req: IdleTimeoutRequest) -> IdleTimeoutResponse:
        """IDLE → RETURNING 자동 복귀 임계값 (초) 변경.

        gogoping_modes 노드의 ROS param ``idle_timeout_seconds`` 를 설정. 동작 노드의
        IdleTimeoutMonitor 가 ``on_set_parameters_callback`` 으로 즉시 ``self._timeout_s``
        + blackboard ``IDLE_TIMEOUT_SECONDS`` 갱신 — 진행 중 카운트다운 (IDLE 중) 도
        새 임계 기준으로 다음 tick 부터 적용.
        """
        if not (1.0 <= req.seconds <= 86400.0):
            raise HTTPException(
                400, f"seconds out of range [1.0, 86400.0]: {req.seconds}"
            )
        bridge.publish_admin_event("idle_timeout", f"seconds={req.seconds}")
        accepted, reason = await asyncio.to_thread(
            bridge.set_idle_timeout_sync, req.seconds,
        )
        if not accepted:
            logger.warning(
                f"SetIdleTimeout 거부: seconds={req.seconds} reason={reason!r}"
            )
        return IdleTimeoutResponse(
            accepted=accepted, reason=reason, seconds=req.seconds,
        )

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
    "HideseekRecruitCompleteRequest", "HideseekRecruitCompleteResponse",
    "HideseekCaughtRequest", "HideseekCaughtResponse",
    "HideseekSkipPhaseRequest", "HideseekSkipPhaseResponse",
]
