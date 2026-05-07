"""AI Hub — FastAPI 의도 분류 엔드포인트.

Vite proxy 가 `/api/voice/intent` 를 이쪽으로 forward.
나중에 Control Service 가 들어오면 Control 이 중간에서 받아 forward.
"""
from typing import Literal

from fastapi import FastAPI, Response
from pydantic import BaseModel, Field

from server.ai.context import build_chat_context
from server.ai.llm import LLMError, classify_intent, generate_chat
from server.ai.robots import STOP_TOKENS, is_known_robot, modes_for
from server.ai.tts import generate_tts

app = FastAPI(title="Pingdergarten AI Hub", version="0.1.0")


class IntentRequest(BaseModel):
    text: str = Field(..., min_length=1)
    robot: Literal["eduping", "gogoping", "noriarm"]


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


def _validate(parsed: dict, robot: str) -> dict:
    """LLM 응답 dict 를 우리 스키마로 검증·정규화. 실패 시 ignored."""
    kind = parsed.get("kind")
    if kind == "mode_change":
        mode = parsed.get("mode", "").strip()
        if mode in modes_for(robot):
            return {"kind": "mode_change", "mode": mode}
        return {"kind": "ignored"}
    if kind == "sub_command":
        action = parsed.get("action")
        if action == "stop":
            return {"kind": "sub_command", "action": "stop"}
        return {"kind": "ignored"}
    return {"kind": "ignored"}


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

    try:
        parsed = await classify_intent(text, req.robot)
    except LLMError:
        # LLM 실패 시 graceful — 무시 처리
        return {"kind": "ignored"}

    validated = _validate(parsed, req.robot)
    if validated["kind"] != "ignored":
        return validated

    # 분류 안 됨 → 잡담 응답 시도. 실패 시 무시
    try:
        ctx = await build_chat_context(text, req.robot)
        chat = await generate_chat(text, req.robot, ctx)
    except LLMError:
        return {
            "kind": "chat",
            "reply": f"{req.robot}은 잘 모르겠어요. 다시 한번 말씀해주실래요?",
            "emotion": "basic"
        }
    return {"kind": "chat", "reply": chat["reply"], "emotion": chat["emotion"]}


@app.get("/voice/tts")
async def get_tts(text: str) -> Response:
    """텍스트를 음성 스트림으로 반환."""
    audio = await generate_tts(text)
    if not audio:
        return Response(status_code=500)
    return Response(content=audio, media_type="audio/mpeg")
