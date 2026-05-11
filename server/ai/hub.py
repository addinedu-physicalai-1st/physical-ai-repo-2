"""AI Hub — FastAPI 의도 분류 엔드포인트.

Vite proxy 가 `/api/voice/intent` 를 이쪽으로 forward.
나중에 Control Service 가 들어오면 Control 이 중간에서 받아 forward.
"""
import asyncio
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from pydantic import BaseModel, Field, field_validator

from server.ai.context import (
    build_chat_context,
    fetch_registered_children_labels,
    try_attendance_first_reply,
    try_report_first_reply,
    try_schedule_first_reply,
    try_whereabouts_first_reply,
)
from server.ai.llm import LLMError, generate_chat
from server.ai.edge_tts_synth import synthesize_edge_mp3
from server.ai.config import settings as ai_settings

from server.ai.guard_replies import teacher_idk_line
from server.ai.robots import STOP_TOKENS, is_known_robot, modes_for, robot_display_name


@asynccontextmanager
async def _hub_lifespan(_: FastAPI):
    if ai_settings.ollama_warmup_on_start:
        from server.ai.llm import warmup_ollama_models

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
    action: Literal["stop"]


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

    name = robot_display_name(robot)

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

    text = req.text.strip()

    # 정지 의도는 명확하므로 LLM 우회 (비용·latency 절감)
    if _is_stop_text(text):
        return {"kind": "sub_command", "action": "stop"}

    # 점심 메뉴 질문은 DB 직접 조회로 우회 (latency 절감)
    _menu_tokens = ("점심", "메뉴", "급식")
    _menu_date_markers = (
        "오늘",
        "내일",
        "어제",
        "그저께",
        "엊그제",
        "모레",
        "글피",
        "그끄저께",
        "하루",
        "이틀",
        "사흘",
        "나흘",
        "닷새",
        "뒤",
        "후",
        "전",
        "전에",
        "이전",
        "만에",
        "뭐",
    )
    if any(kw in text for kw in _menu_tokens) and (
        any(w in text for w in _menu_date_markers) or re.search(r"\d+\s*일", text)
    ):
        from server.ai.context import get_menu_fast, parse_menu_query_calendar_day

        now = datetime.utcnow() + timedelta(hours=9)
        day, relative = parse_menu_query_calendar_day(text, now)

        menu_text = await get_menu_fast(day, relative=relative)
        return {"kind": "chat", "reply": menu_text, "emotion": "happy"}

    # "안녕"에 대한 시간대별 인사 처리
    if text.strip() in ["안녕", "안녕!"]:
        now = datetime.utcnow() + timedelta(hours=9)
        hour = now.hour
        
        if 9 <= hour <= 11:
            reply = "안녕하세요! 좋은 아침이에요! 어서오세요!"
        elif 16 <= hour <= 18:
            reply = "안녕히 가세요! 다음에 또 봐요!"
        else:
            reply = "안녕하세요! 오늘도 만나서 반가워요."
            
        return {"kind": "chat", "reply": reply, "emotion": "hello"}

    # 성별 질문은 규칙 응답 (빠르고 일관되게)
    if _is_gender_question(text):
        return {
            "kind": "chat",
            "reply": "나는 남자아이처럼 말하는 로봇 친구야! 같이 재미있게 이야기하자.",
            "emotion": "happy",
        }

    # 모드 전환 규칙 기반 매칭 (latency 절감)
    for m in modes_for(req.robot):
        if m in text:
            return {"kind": "mode_change", "mode": m}

    # 감정 연기('화내봐' '슬퍼봐' 등) — LLM 이 엉뚱한 말만 할 때가 많아 규칙으로 고정
    demo = _emotion_demo_response(text, req.robot)
    if demo:
        return demo

    # 일과표·시간표 — shared JSON(Control `/api/schedule` 과 동일 원본)을 LLM 보다 먼저
    first_sched = try_schedule_first_reply(text)
    if first_sched:
        return {"kind": "chat", "reply": first_sched, "emotion": "hello"}

    # "OOO 어딨어?" 등 — DB 등하원을 LLM 보다 먼저 (위치 질문 오탐/환각 방지)
    first_where = await try_whereabouts_first_reply(text)
    if first_where:
        return {"kind": "chat", "reply": first_where, "emotion": "interest"}

    # 보고서·일과 — 원아 한 명이 확실할 때 `report` 테이블을 LLM 보다 먼저
    first_report = await try_report_first_reply(text)
    if first_report:
        return {"kind": "chat", "reply": first_report, "emotion": "interest"}

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
            "reply": teacher_idk_line(robot_display_name(req.robot)),
            "emotion": "basic",
        }
    except LLMError:
        name = robot_display_name(req.robot)
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


@app.get("/voice/tts")
async def get_tts(text: str):
    """TTS — Edge neural MP3 (인터넷)."""
    if not text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    try:
        mp3 = await synthesize_edge_mp3(text)
        return Response(content=mp3, media_type="audio/mpeg")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Edge TTS failed: {exc}") from exc

