"""로봇·모드 정의 — shared/robots.json 을 single source of truth 로 공유.

ui/robot-ui/src/config/robots.ts 와 동일한 파일을 읽는다.
"""
import json
from pathlib import Path
from typing import TypedDict

# server/ai/robots.py → repo root → shared/robots.json
_PATH = Path(__file__).resolve().parents[2] / "shared" / "robots.json"


class _RobotEntry(TypedDict):
    id: str
    displayName: str
    wakeWord: str
    modes: list[str]
    defaultEmotionByMode: dict[str, str]
    restrictedVoiceMode: str | None


def _load() -> dict:
    with _PATH.open(encoding="utf-8") as f:
        return json.load(f)


_DATA = _load()
_ROBOTS_BY_ID: dict[str, _RobotEntry] = {r["id"]: r for r in _DATA["robots"]}
MODE_DESCRIPTIONS: dict[str, str] = _DATA["modeDescriptions"]
STOP_TOKENS: list[str] = _DATA["stopTokens"]

ROBOT_MODES: dict[str, list[str]] = {
    rid: entry["modes"] for rid, entry in _ROBOTS_BY_ID.items()
}


def is_known_robot(robot: str) -> bool:
    return robot in _ROBOTS_BY_ID


def modes_for(robot: str) -> list[str]:
    entry = _ROBOTS_BY_ID.get(robot)
    return list(entry["modes"]) if entry else []


def robot_display_name(robot: str) -> str:
    entry = _ROBOTS_BY_ID.get(robot)
    return str(entry["displayName"]) if entry else robot


def capabilities_for(robot: str) -> list[tuple[str, str]]:
    """로봇의 (모드명, 설명) 쌍 — '대기' 제외, capability 만."""
    return [
        (m, MODE_DESCRIPTIONS.get(m, m))
        for m in modes_for(robot)
        if m != "대기"
    ]
