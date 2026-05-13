"""Eduping (OpenArm) REST + WS 엔드포인트.

REST:
  GET    /api/eduping/health
  GET    /api/eduping/dance
  POST   /api/eduping/dance                          (multipart: song + display_name + slug)
  DELETE /api/eduping/dance/{slug}
  POST   /api/eduping/dance/{slug}/record/start
  POST   /api/eduping/dance/{slug}/record/stop       {save: bool}
  POST   /api/eduping/dance/{slug}/play              {target: "sim"|"real", speed: float}
  GET    /api/eduping/greeting
  POST   /api/eduping/greeting/{slot}/record/start   slot ∈ morning|evening
  POST   /api/eduping/greeting/{slot}/record/stop    {save: bool}
  POST   /api/eduping/greeting/{slot}/play           {target, speed}

WS:
  /api/eduping/state         100ms broadcast: leader / follower JointState snapshot
  /api/eduping/recording     100ms broadcast: recording state (active/idle 포함)

teleop 의 `_Hub` 패턴 (asyncio.Queue per client, drop-oldest, daemon broadcaster) 을
WS hub 두 개에 복제. 추후 3 번째 케이스 생기면 server/control/_common 으로 추출 예정.

오디오 (곡) 재생은 다음 PR — 본 라우터는 모션 / 메타까지만.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Literal

from fastapi import (
    APIRouter,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field

from server.control.eduping.ros_bridge import (
    BridgeUnavailable,
    EdupingRosBridge,
    KIND_DANCE,
    KIND_GREETING,
    RecordingConflict,
    RecordingNotActive,
    ros_available,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/eduping", tags=["eduping"])


# WS broadcast 주기
WS_TICK_S = 0.1
QUEUE_MAX = 2

# multipart 업로드 한도 (50MB)
MAX_SONG_BYTES = 50 * 1024 * 1024

ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".m4a"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
GREETING_SLOTS = ("morning", "evening")


def _bridge(req: Request) -> EdupingRosBridge:
    bridge: EdupingRosBridge | None = getattr(req.app.state, "eduping_bridge", None)
    if bridge is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "eduping bridge 가 초기화되지 않았습니다. ROS 환경 (source /opt/ros/jazzy/setup.bash) "
                "과 device/eduping_ws 빌드 완료, shared/ 디렉토리 존재 여부 확인."
            ),
        )
    return bridge


# ---------------------------------------------------------------------------
# request models
# ---------------------------------------------------------------------------


class StopRecordIn(BaseModel):
    save: bool = Field(default=True)


class PlayIn(BaseModel):
    target: Literal["sim", "real"] = "sim"
    speed: float = Field(default=1.0, ge=0.1, le=2.0)


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


@router.get("/health")
async def health(req: Request) -> dict:
    bridge: EdupingRosBridge | None = getattr(req.app.state, "eduping_bridge", None)
    return {
        "ros_available": ros_available(),
        "bridge_running": bridge is not None,
        "routines_root": str(bridge.routines_root) if bridge else None,
    }


# ---------------------------------------------------------------------------
# library — dance
# ---------------------------------------------------------------------------


@router.get("/dance")
async def list_dance(req: Request) -> dict:
    bridge = _bridge(req)
    from eduarm.routines_io import list_dances

    return {"items": list_dances(bridge.routines_root)}


@router.post("/dance", status_code=status.HTTP_201_CREATED)
async def create_dance(
    req: Request,
    slug: str = Form(...),
    display_name: str = Form(...),
    song: UploadFile = File(...),
) -> dict:
    bridge = _bridge(req)
    if not SLUG_RE.match(slug):
        raise HTTPException(400, f"invalid slug; must match {SLUG_RE.pattern}")
    suffix = Path(song.filename or "").suffix.lower()
    if suffix not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(400, f"audio ext {suffix!r} not allowed (allowed: {sorted(ALLOWED_AUDIO_EXTS)})")

    from eduarm.routines_io import (
        dance_dir,
        write_dance_meta,
    )

    dest_dir = dance_dir(bridge.routines_root, slug)
    if dest_dir.exists() and any(dest_dir.iterdir()):
        raise HTTPException(409, f"dance {slug!r} already exists")
    dest_dir.mkdir(parents=True, exist_ok=True)

    song_path = dest_dir / f"song{suffix}"
    written = 0
    try:
        with song_path.open("wb") as f:
            while True:
                chunk = await song.read(1024 * 64)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_SONG_BYTES:
                    raise HTTPException(413, f"song exceeds {MAX_SONG_BYTES} bytes")
                f.write(chunk)
    except HTTPException:
        # cleanup partial write
        if song_path.exists():
            song_path.unlink(missing_ok=True)
        raise

    # 모션은 아직 없음 — duration 0, sample_hz 0
    write_dance_meta(
        bridge.routines_root,
        slug,
        display_name=display_name,
        duration_s=0.0,
        sample_hz=0,
    )

    return {
        "slug": slug,
        "display_name": display_name,
        "song_bytes": written,
        "song_path": str(song_path),
    }


@router.delete("/dance/{slug}")
async def delete_dance(req: Request, slug: str) -> dict:
    bridge = _bridge(req)
    if not SLUG_RE.match(slug):
        raise HTTPException(400, "invalid slug")
    from eduarm.routines_io import dance_dir

    d = dance_dir(bridge.routines_root, slug)
    if not d.exists():
        raise HTTPException(404, "not found")
    shutil.rmtree(d)
    return {"deleted": slug}


@router.post("/dance/{slug}/record/start")
async def dance_record_start(req: Request, slug: str) -> dict:
    bridge = _bridge(req)
    if not SLUG_RE.match(slug):
        raise HTTPException(400, "invalid slug")
    from eduarm.routines_io import dance_dir

    if not dance_dir(bridge.routines_root, slug).exists():
        raise HTTPException(404, f"dance {slug!r} not found — POST /dance 로 먼저 생성")
    try:
        return bridge.start_recording(KIND_DANCE, slug)
    except RecordingConflict as e:
        raise HTTPException(409, str(e)) from e


@router.post("/dance/{slug}/record/stop")
async def dance_record_stop(req: Request, slug: str, body: StopRecordIn) -> dict:
    bridge = _bridge(req)
    try:
        result = bridge.stop_recording(save=body.save)
    except RecordingNotActive as e:
        raise HTTPException(409, str(e)) from e

    # meta.json 의 duration / sample_hz 갱신 (저장된 경우)
    if result.get("saved") and result.get("kind") == KIND_DANCE:
        from eduarm.routines_io import (
            read_dance_meta,
            write_dance_meta,
        )

        meta = read_dance_meta(bridge.routines_root, slug) or {"display_name": slug}
        write_dance_meta(
            bridge.routines_root,
            slug,
            display_name=meta.get("display_name", slug),
            duration_s=float(result.get("duration_s", 0.0)),
            sample_hz=_safe_int(result.get("frame_count", 0) / max(result.get("duration_s", 1), 0.001)),
        )
    return result


@router.post("/dance/{slug}/play")
async def dance_play(req: Request, slug: str, body: PlayIn) -> dict:
    bridge = _bridge(req)
    if not SLUG_RE.match(slug):
        raise HTTPException(400, "invalid slug")
    try:
        return bridge.play_routine(KIND_DANCE, slug, speed=body.speed) | {"target": body.target}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except (ValueError, BridgeUnavailable) as e:
        raise HTTPException(400, str(e)) from e


# ---------------------------------------------------------------------------
# slot — greeting
# ---------------------------------------------------------------------------


@router.get("/greeting")
async def list_greeting(req: Request) -> dict:
    bridge = _bridge(req)
    from eduarm.routines_io import list_greetings

    return {"slots": list_greetings(bridge.routines_root)}


def _check_slot(slot: str) -> None:
    if slot not in GREETING_SLOTS:
        raise HTTPException(400, f"invalid slot; expected one of {GREETING_SLOTS}")


@router.post("/greeting/{slot}/record/start")
async def greeting_record_start(req: Request, slot: str) -> dict:
    _check_slot(slot)
    bridge = _bridge(req)
    try:
        return bridge.start_recording(KIND_GREETING, slot)
    except RecordingConflict as e:
        raise HTTPException(409, str(e)) from e


@router.post("/greeting/{slot}/record/stop")
async def greeting_record_stop(req: Request, slot: str, body: StopRecordIn) -> dict:
    _check_slot(slot)
    bridge = _bridge(req)
    try:
        return bridge.stop_recording(save=body.save)
    except RecordingNotActive as e:
        raise HTTPException(409, str(e)) from e


@router.post("/greeting/{slot}/play")
async def greeting_play(req: Request, slot: str, body: PlayIn) -> dict:
    _check_slot(slot)
    bridge = _bridge(req)
    try:
        return bridge.play_routine(KIND_GREETING, slot, speed=body.speed) | {"target": body.target}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except (ValueError, BridgeUnavailable) as e:
        raise HTTPException(400, str(e)) from e


# ---------------------------------------------------------------------------
# WebSocket hubs (state, recording)
# ---------------------------------------------------------------------------


class _Hub:
    """teleop._Hub 의 simplified 복제. snapshot fn 한 개를 100ms 마다 broadcast.

    한 인스턴스 = 한 WS endpoint. install() 에서 startup/shutdown 훅으로 lifecycle.
    """

    def __init__(self, name: str, snapshot_fn) -> None:
        self._name = name
        self._snapshot_fn = snapshot_fn
        self._clients: list[asyncio.Queue] = []
        self._task: asyncio.Task | None = None
        self._stopped = False

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._broadcaster(), name=f"eduping-hub-{self._name}")

    async def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def add_client(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        self._clients.append(q)
        return q

    def remove_client(self, q: asyncio.Queue) -> None:
        try:
            self._clients.remove(q)
        except ValueError:
            pass

    async def _broadcaster(self) -> None:
        while not self._stopped:
            try:
                snap = self._snapshot_fn()
            except Exception as exc:  # noqa: BLE001
                logger.debug("snapshot 실패 (%s): %s", self._name, exc)
                snap = {"ts": time.time(), "error": str(exc)}
            for q in list(self._clients):
                try:
                    if q.full():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    q.put_nowait(snap)
                except Exception:  # noqa: BLE001
                    continue
            try:
                await asyncio.sleep(WS_TICK_S)
            except asyncio.CancelledError:
                raise


_state_hub: _Hub | None = None
_recording_hub: _Hub | None = None


@router.websocket("/state")
async def ws_state(ws: WebSocket) -> None:
    if _state_hub is None:
        await ws.close(code=1011)
        return
    await ws.accept()
    q = _state_hub.add_client()
    try:
        while True:
            snap = await q.get()
            await ws.send_text(json.dumps(snap))
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("ws_state 종료: %s", exc)
    finally:
        _state_hub.remove_client(q)


@router.websocket("/recording")
async def ws_recording(ws: WebSocket) -> None:
    if _recording_hub is None:
        await ws.close(code=1011)
        return
    await ws.accept()
    q = _recording_hub.add_client()
    try:
        while True:
            snap = await q.get()
            await ws.send_text(json.dumps(snap))
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("ws_recording 종료: %s", exc)
    finally:
        _recording_hub.remove_client(q)


# ---------------------------------------------------------------------------
# wiring — main.py 가 모듈 로드 시 register_router(), lifespan 안에서 start_hubs()/stop_hubs()
# ---------------------------------------------------------------------------


def register_router(app: FastAPI) -> None:
    """모듈 로드 시점에 라우터만 include. bridge 는 아직 없음 (503 응답)."""
    app.include_router(router)


async def start_hubs(app: FastAPI, bridge: EdupingRosBridge) -> None:
    """lifespan startup. bridge 설정 + WS hub 두 개 시작."""
    global _state_hub, _recording_hub
    app.state.eduping_bridge = bridge
    _state_hub = _Hub("state", bridge.state_snapshot)
    _recording_hub = _Hub("recording", bridge.recording_snapshot)
    await _state_hub.start()
    await _recording_hub.start()


async def stop_hubs() -> None:
    """lifespan shutdown."""
    global _state_hub, _recording_hub
    if _state_hub is not None:
        await _state_hub.stop()
        _state_hub = None
    if _recording_hub is not None:
        await _recording_hub.stop()
        _recording_hub = None


# ---------------------------------------------------------------------------
# misc
# ---------------------------------------------------------------------------


def _safe_int(x) -> int:
    try:
        return max(1, int(round(float(x))))
    except Exception:  # noqa: BLE001
        return 50
