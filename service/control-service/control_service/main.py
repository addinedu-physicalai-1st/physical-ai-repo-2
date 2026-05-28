"""Control Service — REST gateway."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

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
from control_service.routers import teachers as teachers_router
from control_service import webrtc_voice as webrtc_voice_router
from control_service.camera_pan.ros_bridge import CameraPanBridge
from control_service.camera_pan.router import install as install_camera_pan
from control_service.gogoping.ros_bridge import GogopingRosBridge
from control_service.gogoping.router import install as install_gogoping
from control_service.routers.gogoping_follow import install as install_gogoping_follow
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
        _gogoping_bridge.start()
    except Exception as e:
        logger.warning(f"gogoping RosBridge 시작 실패 — /api/gogoping/* 503: {e}")

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

    # --- Doctor teleop bridge + 30Hz state push loop ----------------------
    _doctor_state_task: asyncio.Task | None = None
    try:
        doctor_bridge.start()

        async def _doctor_push_loop() -> None:
            import time as _time
            while True:
                await asyncio.sleep(1.0 / 30)
                state = doctor_bridge.latest_state()
                fsr_raw = doctor_bridge.latest_fsr_raw()
                ids = doctor_hub.active_eduping_ids()
                for eid in ids:
                    doctor_hub.publish_state(eid, state)
                if fsr_raw is not None:
                    fsr_evt = {
                        "type": "fsr",
                        "raw": fsr_raw,
                        "ts_ms": int(_time.time() * 1000) & 0xFFFFFFFF,
                    }
                    for eid in ids:
                        doctor_hub.publish_event(eid, fsr_evt)

        _doctor_state_task = asyncio.create_task(_doctor_push_loop())
        app.state.doctor_state_task = _doctor_state_task
        logger.info("Doctor ROS bridge + push loop 시작됨")
    except Exception as e:
        logger.warning(f"Doctor ROS bridge 시작 실패: {e}")

    yield

    if _doctor_state_task is not None:
        _doctor_state_task.cancel()
    try:
        doctor_bridge.shutdown()
    except Exception:
        pass

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
    try:
        _gogoping_bridge.shutdown()
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
app.include_router(teachers_router.router)
app.include_router(webrtc_voice_router.router)

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

# gogoping FSM/BT — SetGoal srv client + /gogoping/state subscriber. /ws/robot-state fan-out.
# waypoints_bridge 도 주입 — /debug/pose 에서 AMCL /initialpose 도 함께 publish (RViz 동기화).
_gogoping_bridge = GogopingRosBridge()
install_gogoping(app, _gogoping_bridge, _waypoints_bridge)
# gogoping follow — POST /api/gogoping/follow/{start,stop} + GET /state
install_gogoping_follow(app, _gogoping_bridge)


# ─── FSM state 전이 ↔ waypoints active goal 동기화 ─────────────────────────────
# BT 와 control-service 가 *각각* graph_router 를 호출할 수 있는 구조라서, BT 가
# 자체 cancel 하더라도 control-service 의 active goal 이 stale 인 채로 남아 admin UI
# (waypoint_map_card) 에 route 잔상이 그려진 상태로 머무는 문제가 있다.
# 해결: state 전이 발생 시 control-service 의 waypoints active goal 도 자동 cancel.
# cancel_current() 는 active 없으면 no-op 이라 idempotent. 새 모드 진입 시 BT 또는
# control-service 가 새 nav 호출하면 그때 다시 active 등록.
# 이 메커니즘은 RETURNING 뿐 아니라 모든 nav 사용 모드 (goto 등) 에 공통 적용.
_prev_fsm_state: dict[str, str | None] = {"value": None}

def _cancel_waypoints_on_state_change(snapshot: dict) -> None:
    new_state = snapshot.get("fsm_state")
    if new_state is None or new_state == _prev_fsm_state["value"]:
        return
    prev = _prev_fsm_state["value"]
    _prev_fsm_state["value"] = new_state
    logger.info(f"[state-change] {prev} → {new_state} — waypoints cancel + plan clear")
    try:
        # 1) graph_router 의 active goal cancel (nav2 까지 forward 됨 — graph_router_node 의 cancel_callback)
        _waypoints_bridge.cancel_current()
        # 2) admin UI 의 update_plan 잔상 제거 — nav2 가 cancel 후 /plan 토픽에 empty
        #    Path 를 publish 안 하므로 control-service 가 직접 SSE 로 empty plan 발송.
        #    waypoint_map_card 의 paint 가 `len(self._plan) >= 2` 가드라 빈 리스트면 안 그림.
        _waypoints_bridge._emit({"type": "plan", "points": []})
        # 3) admin UI 의 set_route (우클릭 미리보기로 그려진 vertex 시퀀스) 도 정리 —
        #    waypoint_map_card 의 _SseHandler.handle 이 goal_status 종료 상태 받으면
        #    set_route(None) 자동 호출.
        _waypoints_bridge._emit({
            "type": "goal_status", "goal_id": "", "status": "canceled",
        })
    except Exception as e:
        logger.warning(f"waypoints cancel on state change failed: {e}")

_gogoping_bridge.register_state_callback(_cancel_waypoints_on_state_change)


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

# Doctor teleop WSS — /ws/doctor/teleop?eduping_id=<id>
from control_service.doctor.teleop_ws import DoctorTeleopHub, build_router as build_doctor_router  # noqa: E402
from control_service.doctor.ros_bridge import DoctorRosBridge  # noqa: E402
from control_service.doctor.pointcloud_relay import (  # noqa: E402
    PointCloudHub,
    build_router as build_doctor_pointcloud_router,
)
from control_service.doctor.eduping_rgb_relay import (  # noqa: E402
    EdupingRgbHub,
    build_router as build_eduping_rgb_router,
)
from control_service.doctor.webrtc_signaling import (  # noqa: E402
    SignalingHub,
    build_router as build_doctor_signal_router,
)

_DOCTOR_LEFT_JOINTS = [f"openarm_left_joint{i+1}" for i in range(7)]
_DOCTOR_RIGHT_JOINTS = [f"openarm_right_joint{i+1}" for i in range(7)]

doctor_hub = DoctorTeleopHub()
doctor_bridge = DoctorRosBridge(left_joints=_DOCTOR_LEFT_JOINTS, right_joints=_DOCTOR_RIGHT_JOINTS)

# doctor_hub → bridge: 타겟 프레임을 ROS 로 publish
doctor_hub.on_target(lambda eid, frame: doctor_bridge.publish_target(frame))

# doctor_hub → bridge: 이벤트 처리
def _on_doctor_event(eid: str, msg: dict) -> None:
    msg_type = msg.get("type")
    if msg_type == "emergency_stop":
        logger.warning("doctor emergency_stop from %s — stop_servo service not yet wired (future task)", eid)
    elif msg_type == "teleop":
        action = msg.get("action")
        active = action == "start"
        ok = doctor_bridge.set_leader_active(active)
        logger.info("doctor teleop %s from %s → leader_passthrough active=%s (ok=%s)",
                    action, eid, active, ok)
    # 기타 메시지는 무시.

doctor_hub.on_event(_on_doctor_event)

app.state.doctor_hub = doctor_hub
app.state.doctor_bridge = doctor_bridge
app.include_router(build_doctor_router(doctor_hub))

# D435 RGB fan-out. producer 는 eduarm d435_rgb_uploader (WS client).
eduping_rgb_hub = EdupingRgbHub()
app.state.eduping_rgb_hub = eduping_rgb_hub
app.include_router(build_eduping_rgb_router(eduping_rgb_hub))

# Doctor ↔ EduPing WebRTC signaling — SDP/ICE 만 relay (미디어는 P2P 직접).
doctor_signal_hub = SignalingHub()
app.state.doctor_signal_hub = doctor_signal_hub
app.include_router(build_doctor_signal_router(doctor_signal_hub))

# PointCloud fan-out — producer 는 eduarm d435_pointcloud_uploader (WS client).
# D435 depth → 1m 필터 + decimate + optical→world 변환은 uploader 측에서 처리.
doctor_pointcloud_hub = PointCloudHub()
app.state.doctor_pointcloud_hub = doctor_pointcloud_hub
app.include_router(build_doctor_pointcloud_router(doctor_pointcloud_hub))

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

# 교사 얼굴 정적 노출 — user.photo_url 은 /api/teacher-faces/{teacher_id}/0.jpg (정면) 형태.
from control_service.routers.teachers import TEACHER_FACE_DIR  # noqa: E402
os.makedirs(TEACHER_FACE_DIR, exist_ok=True)
app.mount(
    "/api/teacher-faces",
    StaticFiles(directory=TEACHER_FACE_DIR),
    name="teacher-faces",
)


class ModeRequest(BaseModel):
    robot: Literal["eduping", "gogoping", "noriarm"]
    mode: str


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


# /api/voice/intent, /api/voice/tts, /api/stt 는 WebRTC 마이그레이션 후 모두 제거.
# 음성 흐름은 `/api/voice/webrtc/offer` 단일 진입점 (webrtc_voice.py) 으로 통합:
# 인바운드 audio → Silero VAD → whisper, intent dispatch → outbound TTS, DataChannel 제어.


@app.post("/api/mode")
async def mode_click(req: ModeRequest) -> dict:
    """모드 셀렉터 UI 클릭 — robot id 별 routing.

    - ``gogoping`` → ``_gogoping_bridge.send_goal_sync`` (mode_to_goal 변환 후 SetGoal.srv).
      HIDEANDSEEK 진입 시 yaml 의 group 셔플된 vertex 로 search_waypoints 동적 채움 +
      patrol_only=False 명시 cleanup — ``/api/gogoping/mode`` 와 동일 흐름.
    - ``eduping`` / ``noriarm`` — 현재 단순 로그 + ok 반환. 추후 각 brige 로 라우팅.
    """
    if req.robot == "gogoping":
        from control_service.gogoping.state_to_goal import UnsupportedMode, mode_to_goal
        from control_service.gogoping.router import _build_hideseek_goal_dynamic

        try:
            goal = mode_to_goal(req.mode)
        except UnsupportedMode as e:
            raise HTTPException(400, str(e))

        # HIDEANDSEEK 진입 — search_waypoints 동적 채움 + patrol_only=False 셋팅.
        # 두 endpoint (/api/mode, /api/gogoping/mode) 동작 일치해야 robot-web 클릭이 어느 쪽으로 가도 OK.
        if goal.target_state == "HIDEANDSEEK":
            goal = await asyncio.to_thread(
                _build_hideseek_goal_dynamic, _gogoping_bridge, goal,
            )
            await asyncio.to_thread(_gogoping_bridge.write_hideseek_patrol_only, False)

        accepted, reason = await asyncio.to_thread(_gogoping_bridge.send_goal_sync, goal)
        if not accepted:
            logger.warning(
                f"SetGoal 거부: mode={req.mode!r} → Goal({goal.to_dict()}) reason={reason!r}"
            )
        return {
            "ok": accepted,
            "robot": req.robot,
            "mode": req.mode,
            "reason": reason,
            "goal_target_state": goal.target_state,
        }

    # eduping / noriarm — TODO: 각 robot 의 router 가 mode 클릭 처리하면 그쪽으로 라우팅.
    return {"ok": True, "robot": req.robot, "mode": req.mode}
