"""AI Hub — FastAPI 의도 분류 엔드포인트.

Vite proxy 가 `/api/voice/intent` 를 이쪽으로 forward.
나중에 Control Service 가 들어오면 Control 이 중간에서 받아 forward.
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse

from pydantic import BaseModel, Field, field_validator

from ai_service.vision import OXBoardTask, default_registry

logger = logging.getLogger(__name__)

from ai_service.capabilities.schedule_file import load_school_schedule_dict
from ai_service.llm import LLMError, generate_report
from ai_service.edge_tts_synth import synthesize_edge_mp3_stream
from ai_service.config import settings as ai_settings

from ai_service.robots import STOP_TOKENS, is_known_robot, modes_for


@asynccontextmanager
async def _hub_lifespan(_: FastAPI):
    # Vision task 등록 — lifespan 을 지정하면 @app.on_event("startup") 핸들러는
    # 무시되므로 (FastAPI 0.93+) 여기서 직접 등록.
    if not default_registry.names():
        default_registry.register(OXBoardTask())
        logger.info(f"AI Hub vision tasks: {default_registry.names()}")
    if ai_settings.ollama_warmup_on_start:
        from ai_service.llm import warmup_ollama_models

        asyncio.create_task(warmup_ollama_models())
    yield


app = FastAPI(
    title="Pingdergarten AI Hub",
    version="0.1.0",
    lifespan=_hub_lifespan,
)


class IntentRequest(BaseModel):
    text: str = Field(..., min_length=1)
    robot: Literal["eduping", "gogoping", "noriarm"]
    # 로봇 UI가 반 명단을 알 때만 보냄 — LLM 에 사실로 주입 (없으면 이름 질문에 환각 방지용 안내만)
    class_roster: list[str] = Field(default_factory=list, max_length=40)

    @field_validator("class_roster", mode="before")
    @classmethod
    def _strip_roster(cls, v: object) -> object:
        if not isinstance(v, list):
            return v
        out: list[str] = []
        for item in v:
            if not isinstance(item, str):
                continue
            s = item.strip()
            if s and len(s) <= 32:
                out.append(s)
        return out[:40]


class ModeChange(BaseModel):
    kind: Literal["mode_change"] = "mode_change"
    mode: str


class SubCommand(BaseModel):
    kind: Literal["sub_command"] = "sub_command"
    action: Literal["stop", "return"]


class GotoVertex(BaseModel):
    """vertex 이름으로 graph routing 이동 — gogoping 보조 모드 전용."""
    kind: Literal["goto_vertex"] = "goto_vertex"
    name: str


class Chat(BaseModel):
    kind: Literal["chat"] = "chat"
    reply: str
    emotion: str


class Ignored(BaseModel):
    kind: Literal["ignored"] = "ignored"


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


class ModeChangeRequest(BaseModel):
    robot: Literal["eduping", "gogoping", "noriarm"]
    mode: str


@app.post("/mode")
async def post_mode(req: ModeChangeRequest) -> dict:
    """모드 셀렉터 UI 클릭 — 의도 분류 거치지 않고 단순 ack.
    Control Service 가 들어오면 그쪽이 ROS2 latched topic 발행 + DB 기록 담당.
    """
    if req.mode not in modes_for(req.robot):
        return {"ok": False, "error": "unknown mode"}
    return {"ok": True, "robot": req.robot, "mode": req.mode}


@app.post("/voice/intent")
async def voice_intent(req: IntentRequest) -> dict:
    if not is_known_robot(req.robot):
        return {"kind": "ignored"}

    # Inline import: hub.py defines the Pydantic models (IntentRequest, Chat, ...)
    # that intents/* modules import. Module-level import here would cycle.
    from ai_service.intents import PIPELINES, IntentContext, now_kst
    ctx = IntentContext(now=now_kst(), req=req)
    for handler in PIPELINES[req.robot]:
        result = await handler.try_handle(req, ctx)
        if result is not None:
            logger.info(
                "intent.matched",
                extra={"robot": req.robot, "handler": handler.name},
            )
            return result.model_dump()
    raise RuntimeError("no handler matched — ChatFallback missing?")


class ReportPhotoEvent(BaseModel):
    photo_id: int
    time: str  # "HH:MM"
    robot: str
    mode: str
    emotion: str
    score: str  # "0.82"


class ReportAttendanceIn(BaseModel):
    check_in_kst: str | None = Field(None, max_length=8)
    check_out_kst: str | None = Field(None, max_length=8)


class ReportGenerateRequest(BaseModel):
    child_name: str = Field(..., min_length=1, max_length=32)
    registered_full_name: str | None = Field(None, max_length=64)
    class_name: str = Field(..., min_length=1, max_length=64)
    birth_date: str = Field(..., min_length=10, max_length=10)  # "YYYY-MM-DD"
    date: str = Field(..., min_length=10, max_length=10)  # 보고서 일자
    photo_events: list[ReportPhotoEvent] = Field(default_factory=list, max_length=200)
    menu_items: list[str] = Field(default_factory=list, max_length=20)
    child_notes: str | None = Field(None, max_length=4000)
    attendance: ReportAttendanceIn | None = None


@app.post("/report/generate")
async def post_report_generate(req: ReportGenerateRequest) -> dict:
    """자녀 한 명의 하루치 일과 보고서 — 자연 촬영 메타 + 점심메뉴 기반 자연어 요약.

    Control Server 가 데이터 수집 후 forward. SR-RPT-001 의 동기 변형 — `ai_job` 큐
    도입 전 임시 경로.
    """
    try:
        sched = load_school_schedule_dict()
        att = req.attendance.model_dump() if req.attendance else None
        body = await generate_report(
            child_name=req.child_name,
            registered_full_name=req.registered_full_name,
            class_name=req.class_name,
            birth_date_str=req.birth_date,
            date_str=req.date,
            photo_events=[p.model_dump() for p in req.photo_events],
            menu_items=req.menu_items,
            schedule=sched,
            child_notes=req.child_notes,
            attendance=att,
        )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=f"LLM failed: {exc}") from exc
    return {"content": body}


@app.get("/voice/tts")
async def get_tts(text: str):
    """TTS — Edge neural MP3 스트리밍. chunk 단위로 흘려보내 첫 음성 latency 단축."""
    if not text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    try:
        return StreamingResponse(
            synthesize_edge_mp3_stream(text),
            media_type="audio/mpeg",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Edge TTS failed: {exc}") from exc


# ---------- Vision (task-based YOLO 추론) ----------

@app.get("/vision/tasks")
async def vision_tasks() -> dict:
    """등록된 vision task 목록."""
    return {"tasks": default_registry.list_tasks()}


@app.post("/vision/{task}/infer")
async def vision_infer(task: str, req: Request) -> dict:
    """1회성 추론 (디버깅·curl 용). 스트리밍은 WebSocket 권장.

    body=image/jpeg → 해당 task YOLO → bbox JSON.
    """
    t = default_registry.get(task)
    if t is None:
        raise HTTPException(status_code=404, detail=f"unknown vision task: {task!r}")
    body = await req.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty body")
    try:
        return await asyncio.to_thread(t.infer, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.websocket("/vision/{task}/infer")
async def vision_infer_ws(ws: WebSocket, task: str) -> None:
    """스트리밍 추론 — 브라우저가 frame binary 보내면 추론 결과 JSON 으로 응답.

    프로토콜:
      client → server : binary (image/jpeg)
      server → client : text (JSON 결과 = vision_infer 와 동일 schema)
    """
    t = default_registry.get(task)
    if t is None:
        await ws.accept()
        await ws.close(code=1008, reason=f"unknown vision task: {task}")
        return

    await ws.accept()
    logger.info("vision ws 접속 — task=%s", task)
    try:
        while True:
            jpeg = await ws.receive_bytes()
            if not jpeg:
                continue
            try:
                result = await asyncio.to_thread(t.infer, jpeg)
            except ValueError as e:
                await ws.send_json({"error": str(e)})
                continue
            await ws.send_json(result)
    except WebSocketDisconnect:
        logger.info("vision ws 퇴장 — task=%s", task)
