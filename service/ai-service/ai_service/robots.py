"""로봇·모드 정의 — shared/robots.json 을 single source of truth 로 공유.

service/web-service/robot-web/src/config/robots.ts 와 동일한 파일을 읽는다.
"""
import json
from pathlib import Path
from typing import TypedDict

# service/ai-service/ai_service/robots.py → repo root → shared/robots.json
_PATH = Path(__file__).resolve().parents[3] / "shared" / "robots.json"


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


def name_aliases_for(robot: str) -> frozenset[str]:
    """로봇을 부르는 이름들 (wakeWord + wakeWordAliases + displayName).

    소문자로 정규화된 frozenset. wake-name 매칭에 사용.
    """
    entry = _ROBOTS_BY_ID.get(robot)
    if not entry:
        return frozenset()
    names: set[str] = set()
    if entry.get("wakeWord"):
        names.add(entry["wakeWord"].lower())
    for alias in entry.get("wakeWordAliases", []) or []:
        if alias:
            names.add(alias.lower())
    if entry.get("displayName"):
        names.add(entry["displayName"].lower())
    return frozenset(names)
