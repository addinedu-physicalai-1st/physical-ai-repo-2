"""감정 정의 로더 — shared/emotions.json 을 single source of truth 로 공유.

프론트엔드 `ui/robot-ui/src/config/emotions.ts` 와 동일한 파일을 읽는다.
"""
import json
from pathlib import Path
from typing import TypedDict

# server/ai/emotions.py → repo root → shared/emotions.json
_PATH = Path(__file__).resolve().parents[2] / "shared" / "emotions.json"


class EmotionDef(TypedDict):
    id: str
    label: str
    description: str
    chat_eligible: bool


def _load() -> list[EmotionDef]:
    with _PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    return data["emotions"]


EMOTIONS: list[EmotionDef] = _load()
ALL_EMOTION_IDS: list[str] = [e["id"] for e in EMOTIONS]
CHAT_EMOTIONS: list[EmotionDef] = [e for e in EMOTIONS if e["chat_eligible"]]
CHAT_EMOTION_IDS: list[str] = [e["id"] for e in CHAT_EMOTIONS]


def is_chat_emotion(value: str) -> bool:
    return value in CHAT_EMOTION_IDS
