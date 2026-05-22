"""Streaming app — port 9100/TCP, /ws/video-stream + /api/streaming/*.

PLAN §4.2 — 별도 uvicorn 프로세스. SR-CAM-002, SR-CAM-005.

실행:
  uvicorn control_service.streaming.app:app --host 0.0.0.0 --port 9100
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI

from control_service.streaming import config as scfg
from control_service.streaming.admin_router import make_admin_router
from control_service.streaming.client_registry import ClientRegistry
from control_service.streaming.depth_hub import DepthHub
from control_service.streaming.depth_ws_router import make_depth_ws_router
from control_service.streaming.frame_hub import FrameHub
from control_service.streaming.robot_controller import RobotController
from control_service.streaming.udp_receiver import UdpFrameReceiver
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


@app.on_event("startup")
async def _on_startup() -> None:
    logging.basicConfig(
        level=os.environ.get("STREAMING_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    loop = asyncio.get_running_loop()

    # 로봇별 UDP 수신 스레드 시작 — 이번 SR 은 IP 등록된 로봇의 primary stream 만
    started = []
    for robot_id in sorted(scfg.ROBOT_HOST.keys()):
        if not _controller.has_robot(robot_id):
            continue   # IP 미등록 (eduping/noriarm 추후 SR) → skip
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
