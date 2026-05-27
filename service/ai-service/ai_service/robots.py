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


def _voice_excluded_modes(entry: _RobotEntry) -> set[str]:
    """modeTree 에서 `voiceExcluded: true` 그룹의 모든 자손 mode id 를 모은다.
    음성 명령으로 진입을 차단할 모드 (예: 관리 메뉴 하위) 식별용."""
    excluded: set[str] = set()

    def walk(node, inside_excluded: bool) -> None:
        if isinstance(node, str):
            if inside_excluded:
                excluded.add(node)
            return
        if isinstance(node, dict):
            group_excluded = inside_excluded or bool(node.get("voiceExcluded"))
            for child in node.get("children", []):
                walk(child, group_excluded)

    for top in entry.get("modeTree", []) or []:
        walk(top, False)
    return excluded


def mode_matchers_for(robot: str) -> list[tuple[str, str]]:
    """[(키워드, 대상 mode), ...] — modes 의 정식 이름 + modeAliases 의 별칭.

    길이 내림차순 정렬. ModeChangeHandler 가 substring 매치 시
    '율동 등록' (긴 mode) 이 '율동' (짧은 mode) 보다 먼저 시도되어
    부분-키워드 충돌을 피한다.

    modeTree 에서 `voiceExcluded: true` 로 표시된 그룹의 자손 mode 는 제외.
    """
    entry = _ROBOTS_BY_ID.get(robot)
    if not entry:
        return []
    aliases: dict[str, list[str]] = entry.get("modeAliases", {}) or {}  # type: ignore[assignment]
    excluded = _voice_excluded_modes(entry)
    out: list[tuple[str, str]] = []
    for mode in entry["modes"]:
        if mode in excluded:
            continue
        out.append((mode, mode))
        for alias in aliases.get(mode, []):
            if alias:
                out.append((alias, mode))
    out.sort(key=lambda kv: -len(kv[0]))
    return out


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


def wake_words_for(robot: str) -> list[str]:
    """STT prompt biasing 용 — wakeWord + aliases. 다른 robot 이름은 제외해
    Whisper 가 짧은 발화를 다른 robot 후보로 떨어트리는 것을 막는다."""
    entry = _ROBOTS_BY_ID.get(robot)
    if not entry:
        return []
    names = [entry["wakeWord"]] if entry.get("wakeWord") else []
    for alias in entry.get("wakeWordAliases", []) or []:
        if alias:
            names.append(alias)
    return names


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
