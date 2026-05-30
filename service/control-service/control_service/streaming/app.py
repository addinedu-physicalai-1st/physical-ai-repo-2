"""Streaming app — port 9100/TCP, /ws/video-stream + /api/streaming/*.

PLAN §4.2 — 별도 uvicorn 프로세스. SR-CAM-002, SR-CAM-005.

실행:
  uvicorn control_service.streaming.app:app --host 0.0.0.0 --port 9100
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from control_service.streaming import config as scfg
from control_service.streaming.admin_router import make_admin_router
from control_service.streaming.client_registry import ClientRegistry
from control_service.streaming.debug_router import make_debug_router, start_tracemalloc
from control_service.streaming.depth_hub import DepthHub
from control_service.streaming.depth_ws_router import make_depth_ws_router
from control_service.streaming.frame_hub import FrameHub
from control_service.streaming.robot_controller import RobotController
from control_service.streaming.udp_receiver import UdpFrameReceiver
from control_service.streaming.webrtc_router import router as webrtc_router
from control_service.streaming.ws_router import make_ws_router


_log = logging.getLogger("streaming.app")


app = FastAPI(title="Pingdergarten Streaming", version="0.1.0")

# 모듈 전역 — uvicorn 단일 worker 가정.
_hub = FrameHub()
# D435 depth 스트림 fan-out 용 별도 hub. 영상 (FrameHub) 과 인터페이스만 비슷할 뿐
# 와이어 포맷 (uint16 depth + JPEG color) 이 달라서 분리.
_depth_hub = DepthHub()
_registry = ClientRegistry()
_controller = RobotController()
_receivers: list[UdpFrameReceiver] = []

app.include_router(make_admin_router(_controller))
app.include_router(make_ws_router(_registry, _hub))
# /ws/depth-stream/producer/{robot} + /ws/depth-stream (consumer) — 4b98dc6 에서
# 모듈은 추가됐는데 여기 include 가 빠져있어 producer connect 가 HTTP 403 (route
# 미등록) 으로 막혔던 것. eduping D435 streamer 가 이 producer 로 frame 을 push.
app.include_router(make_depth_ws_router(_registry, _depth_hub))
# WebRTC signaling — /ws/webrtc/signaling (gogoping D435 RTSP-less stream)
app.include_router(webrtc_router)
# /debug/mem* — RAM 누수 추적 (2026-05-30 OOM). STREAMING_TRACEMALLOC=0 으로 끔.
app.include_router(make_debug_router())

# admin-app (PyQt QWebEngineView) 의 OpenSSL 1.x ↔ 시스템 3.x 호환성 문제로 vite
# (mkcert https) self-signed cert 검증 실패. 우회 path: robot-web 의 production
# build (dist-admin/, base=/admin-embed/) 를 HTTP /admin-embed/ 로 serve.
#
# 일반 dist/ 와 분리한 이유: dist/ 는 absolute path (`/assets/...`) 라 root mount
# 가정. /admin-embed/ subpath mount 에선 asset 404. dist-admin/ 는 base=/admin-embed/
# 로 빌드돼 subpath 에서도 asset 경로 정상.
#
# 빌드: cd service/web-service/robot-web && npm run build:admin
# Path override: ROBOT_WEB_ADMIN_DIST env.
_default_admin_dist = (
    Path(__file__).resolve().parents[3] / "web-service" / "robot-web" / "dist-admin"
)
_robot_web_admin_dist = Path(os.environ.get("ROBOT_WEB_ADMIN_DIST", str(_default_admin_dist)))
if _robot_web_admin_dist.is_dir():
    app.mount(
        "/admin-embed",
        StaticFiles(directory=str(_robot_web_admin_dist), html=True),
        name="admin-embed",
    )
    _log.info("admin-embed mounted at %s", _robot_web_admin_dist)
else:
    _log.warning(
        "admin-embed dir 없음 (%s) — admin QWebEngineView 가 https 우회 못 함. "
        "service/web-service/robot-web 에서 'npm run build:admin' 필요",
        _robot_web_admin_dist,
    )


@app.on_event("startup")
async def _on_startup() -> None:
    logging.basicConfig(
        level=os.environ.get("STREAMING_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    # RAM 누수 추적 baseline (2026-05-30 OOM). /debug/memtop 으로 diff 확인.
    start_tracemalloc()
    loop = asyncio.get_running_loop()

    # 로봇별 UDP 수신 스레드 시작 — 이번 SR 은 IP 등록된 로봇의 primary stream 만
    started = []
    gogoping_id = scfg.ROBOT_IDS["gogoping"]
    for robot_id in sorted(scfg.ROBOT_HOST.keys()):
        if not _controller.has_robot(robot_id):
            continue   # IP 미등록 (eduping/noriarm 추후 SR) → skip
        if robot_id == gogoping_id and not scfg.settings.gogoping_udp_enabled:
            _log.info(
                "gogoping UDP receiver skipped (WebRTC migration, "
                "set STREAMING_GOGOPING_UDP_ENABLED=true to re-enable)"
            )
            continue
        port = scfg.video_port(robot_id, stream_id=0)
        rcv = UdpFrameReceiver(robot_id=robot_id, port=port, hub=_hub, loop=loop)
        rcv.start()
        _receivers.append(rcv)
        started.append((scfg.ID_TO_NAME[robot_id], port))

    _log.info(
        "streaming app ready — port=%d, receivers=%s",
        scfg.settings.streaming_port, started,
    )

    # 부팅 sanity check (PLAN §3.6)
    asyncio.create_task(_boot_sanity_check())


async def _boot_sanity_check() -> None:
    """Server 부팅 후 5초간 frame 수신 모니터, 미수신 시 START 1회 송신."""
    delay = scfg.settings.boot_check_delay_s
    await asyncio.sleep(delay)
    for rcv in _receivers:
        if rcv.frames_received == 0:
            _log.warning(
                "robot %d (port %d) frame %ds 미수신 → START 송신",
                rcv.robot_id, rcv.port, int(delay),
            )
            await _controller.manual_start(rcv.robot_id)


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    for rcv in _receivers:
        rcv.stop()
    _controller.close()


@app.get("/health")
async def health() -> dict:
    """헬스 + 메트릭."""
    return {
        "ok": True,
        "clients": _registry.count(),
        "subscriber_counts": {
            f"{scfg.ID_TO_NAME.get(rid, rid)}/{sid}": cnt
            for (rid, sid), cnt in _hub.snapshot_counts().items()
        },
        "udp_receivers": [
            {
                "robot": scfg.ID_TO_NAME.get(r.robot_id, r.robot_id),
                "port": r.port,
                "frames_received": r.frames_received,
                "frames_dropped": r.frames_dropped,
            }
            for r in _receivers
        ],
        "registered_robots": [
            scfg.ID_TO_NAME[rid] for rid in _controller.known_robots()
        ],
    }
