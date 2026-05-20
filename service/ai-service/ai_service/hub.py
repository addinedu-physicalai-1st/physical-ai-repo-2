"""AI Hub — FastAPI 의도 분류 엔드포인트.

Vite proxy 가 `/api/voice/intent` 를 이쪽으로 forward.
나중에 Control Service 가 들어오면 Control 이 중간에서 받아 forward.
"""
import asyncio
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse

from pydantic import BaseModel, Field, field_validator

from ai_service.vision import OXBoardTask, default_registry

logger = logging.getLogger(__name__)

from ai_service.context import build_chat_context
from ai_service.capabilities.db_attendance import (
    try_attendance_first_reply,
    try_whereabouts_first_reply,
)
from ai_service.capabilities.db_report import try_report_first_reply
from ai_service.capabilities.db_roster import fetch_registered_children_labels
from ai_service.capabilities.schedule_file import (
    load_school_schedule_dict,
    try_schedule_first_reply,
)
from ai_service.llm import LLMError, generate_chat, generate_report
from ai_service.edge_tts_synth import synthesize_edge_mp3_stream
from ai_service.config import settings as ai_settings

from ai_service import prompts
from ai_service.guard_replies import teacher_idk_line
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


def _is_stop_text(text: str) -> bool:
    lower = text.lower()
    return any(tok in lower for tok in [t.lower() for t in STOP_TOKENS])


def _normalize_utterance(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text.lower())


def _needs_chat_fallback(user_text: str, reply: str) -> bool:
    """LLM 이 입력 에코/무의미 반복을 낼 때 재시도 없이 안전 문구로 교체."""
    u = _normalize_utterance(user_text)
    r = _normalize_utterance(reply)
    if not u or not r:
        return True
    if u == r:
        return True
    # 매우 짧은 응답인데 사용자 입력을 거의 그대로 반복하면 fallback
    if len(r) <= max(8, len(u) + 2) and (u in r or r in u):
        return True
    return False


# ── 복귀 ("돌아가" / "복귀" / "충전") ──────────────────────────────────────
_RETURN_TOKENS = ("복귀", "돌아가", "돌아와", "충전소", "충전하러", "충전 하러")


def _is_return_text(text: str) -> bool:
    """RETURNING state 진입 trigger 발화 매칭."""
    t = text.strip()
    if not t:
        return False
    return any(tok in t for tok in _RETURN_TOKENS)


# ── "X로 가" / "X로 이동해줘" — vertex name 추출 ────────────────────────────
_GOTO_PATTERNS = (
    "로 가",
    "로 이동",
    "에 가",
    "로 갑",
    "에 갑",
    "로 갈",
    "에 갈",
    "로 향",
    "로 와",
    "에 와",
    " 가자",
    " 가줘",
    " 가",
)


def _load_vertex_names() -> list[str]:
    """waypoints.yaml 의 vertex name 목록. yaml read 는 가벼움 (한 번에 < 1ms)."""
    try:
        from control_service.waypoints import yaml_store as ys
        wps, _ = ys.load()
        return [w.name for w in wps]
    except Exception:
        return []


def _try_goto_vertex(text: str) -> str | None:
    """발화에 vertex name + goto 패턴이 모두 있으면 vertex name 반환.

    매칭 우선순위: 더 긴 vertex name 먼저 (예: '운동장11' 이 '운동장' 보다 먼저).
    """
    t = text.strip()
    if not t:
        return None
    # goto 패턴이 하나라도 있어야
    if not any(p in t for p in _GOTO_PATTERNS):
        return None
    names = sorted(_load_vertex_names(), key=len, reverse=True)
    for name in names:
        if name and name in t:
            return name
    return None


def _is_gender_question(text: str) -> bool:
    compact = _normalize_utterance(text)
    if not compact:
        return False
    gender_tokens = ("성별", "남자", "여자", "boy", "girl", "male", "female")
    ask_tokens = ("너", "로봇", "누구", "뭐")
    return any(t in compact for t in gender_tokens) and (
        any(t in compact for t in ask_tokens) or "야" in text or "인가" in text
    )


def _emotion_demo_response(text: str, robot: str) -> dict | None:
    """'화내봐' '슬퍼봐' 등 감정 연기 요청 — LLM 우회."""
    raw = text.strip()
    if len(raw) > 36:
        return None
    if "지마" in raw or "하지마" in raw.replace(" ", ""):
        return None
    c = re.sub(r"[\s\.,!?…:]+", "", raw)
    if not c:
        return None

    imperatives = ("봐", "줘", "해봐", "해줘", "할래", "연기", "흉내", "해줄래")
    has_imperative = any(m in raw for m in imperatives)
    if len(c) > 10 and not has_imperative:
        return None

    name = prompts.display_name(robot)

    if any(k in c for k in ("화내", "화나", "짜증", "빡쳐", "열받", "분노")):
        return {
            "kind": "chat",
            "reply": f"으… {name} 화났어! 금방 가라앉힐게.",
            "emotion": "angry",
        }
    if any(k in c for k in ("슬프", "슬퍼", "우울", "서글")):
        return {
            "kind": "chat",
            "reply": f"흑… 너무 슬퍼. {name}이 같이 있어줄게.",
            "emotion": "sad",
        }
    if any(k in c for k in ("울어", "눈물", "엉엉")):
        return {
            "kind": "chat",
            "reply": f"으응… 울어도 괜찮아. {name}이 옆에 있어줄게.",
            "emotion": "sad",
        }
    if any(k in c for k in ("웃어", "웃자", "행복", "기뻐", "신나")):
        return {
            "kind": "chat",
            "reply": f"헤헤! {name}도 신나! 같이 웃자!",
            "emotion": "happy",
        }
    if "심심" in c:
        return {
            "kind": "chat",
            "reply": "심심해? 같이 뭐 재미있는 거 해볼까?",
            "emotion": "bored",
        }
    if any(k in c for k in ("졸려", "잘래", "자고", "쿨쿨")):
        return {
            "kind": "chat",
            "reply": "쿨… 잠이 와… 조금만 눈 붙일게…",
            "emotion": "sleep",
        }
    if "재밌" in c:
        return {
            "kind": "chat",
            "reply": "좋아! 재미있게 놀아보자!",
            "emotion": "fun",
        }
    return None


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

    text = req.text.strip()

    # ── 디스패처가 아직 매칭 못 한 케이스는 아래 기존 if-블록이 처리 ──
    # (앞으로 핸들러를 옮기면서 한 블록씩 삭제)

    # 복귀 / 충전 (gogoping 만 의미 있음 — 다른 로봇은 ignored)
    if req.robot == "gogoping" and _is_return_text(text):
        return {"kind": "sub_command", "action": "return"}

    # vertex 이동 ("X로 가") — gogoping 보조 모드 전용. graph_router 가 처리.
    # mode_change 매칭 전에 시도 (vertex 이름이 mode 와 겹치지 않으면 안전).
    if req.robot == "gogoping":
        vname = _try_goto_vertex(text)
        if vname is not None:
            return {"kind": "goto_vertex", "name": vname}

    # 이름만 입력 시 등하원 규칙 답변 (소형 LLM 의 아이 말투 환각 방지)
    first_att = await try_attendance_first_reply(text)
    if first_att:
        return {"kind": "chat", "reply": first_att, "emotion": "hello"}

    # 분류 안 됨 → 잡담 응답 시도. 컨텍스트 + 명단 DB 는 병렬로 가져와 레이턴시 절감
    ctx: dict[str, str] = {}
    db_roster: str | None = None
    c_out, roster_out = await asyncio.gather(
        build_chat_context(text, req.robot),
        fetch_registered_children_labels(),
        return_exceptions=True,
    )
    if not isinstance(c_out, BaseException):
        ctx = c_out
    if not isinstance(roster_out, BaseException):
        db_roster = roster_out
    if db_roster:
        ctx["registered_children"] = db_roster
    elif req.class_roster:
        ctx["registered_children"] = ", ".join(req.class_roster)

    cap = float(ai_settings.voice_chat_llm_max_wait_s or 0.0)
    try:
        if cap > 0:
            chat = await asyncio.wait_for(
                generate_chat(text, req.robot, ctx),
                timeout=cap,
            )
        else:
            chat = await generate_chat(text, req.robot, ctx)
    except asyncio.TimeoutError:
        return {
            "kind": "chat",
            "reply": teacher_idk_line(prompts.display_name(req.robot)),
            "emotion": "basic",
        }
    except LLMError:
        name = prompts.display_name(req.robot)
        return {
            "kind": "chat",
            "reply": f"{name}에게 잠깐 연결 문제가 생겼어요. 다시 한번 말해줄래요?",
            "emotion": "basic",
        }
    if _needs_chat_fallback(text, chat.get("reply", "")):
        return {
            "kind": "chat",
            "reply": "알겠어요! 도와달라는 말로 이해했어요. 무엇이 필요한지 한 번만 더 말해줄래요?",
            "emotion": "interest",
        }
    return {"kind": "chat", "reply": chat["reply"], "emotion": chat["emotion"]}


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
