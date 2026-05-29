"""gogoping 전용 — 'X로 가' / 'X에 가' vertex routing.

추가 기능:
- vertex alias — 자연어 구절("밖으로 나가")을 특정 vertex(운동장)로 매핑. vertex 이름을
  직접 안 말해도 이동. (별칭은 goto 패턴 없이도 트리거 — 구절 자체가 이동 의도)
- then_mode — 복합 명령 "X 가서 자장가" → 도착 후 모드 전환. 정보불필요 모드
  (자장가/수동/대기) 만. 순서 제어는 robot-web(client) 가 담당.
"""
from __future__ import annotations

from typing import ClassVar

from ai_service.hub import GotoVertex, IntentRequest
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse

_GOTO_PATTERNS = (
    "로 가", "로 이동", "에 가", "로 갑", "에 갑", "로 갈",
    "에 갈", "로 향", "로 와", "에 와", " 가자", " 가줘", " 가",
)

# 자연어 구절 → vertex 이름. 구체 구절만 (오탐 방지). 값은 waypoints.yaml 의 실제 vertex.
_VERTEX_ALIASES: dict[str, str] = {
    "밖으로 나가": "운동장",
    "밖에 나가": "운동장",
    "밖으로 나가자": "운동장",
    "밖에 나가자": "운동장",
    "밖으로 가": "운동장",
    "밖에 가": "운동장",
    "바깥으로 나가": "운동장",
    "바깥에 나가": "운동장",
}

# STT 오인식 보정 — vertex 이름 변형 → 정식 vertex. goto 패턴과 함께일 때만 매칭(오탐 방지).
# 정식 이름 매칭이 먼저 시도되고, 실패 시에만 fallback. 부분문자열이라 변형들을 한 번에 흡수:
#   "면실" ⊂ "수면실"/"일면실"/"면실" → STT 가 첫 음절 흘려도 수면실로 라우팅.
_VERTEX_NAME_ALIASES: dict[str, str] = {
    "면실": "수면실",
}

# 도착 후 전환할 모드 (정보불필요 모드만 — 추가 대상/장소 불필요).
# vertex 이름에 없는 토큰만 골라 오탐 방지: 자장가/수동/대기.
_THEN_MODE_KEYWORDS: dict[str, str] = {
    "자장가": "자장가",
    "수동": "수동",
    "대기": "대기",
}


def _load_vertex_names() -> list[str]:
    """waypoints.yaml 의 vertex name 목록. yaml read 는 가벼움 (< 1ms)."""
    try:
        from control_service.waypoints import yaml_store as ys
        wps, _ = ys.load()
        return [w.name for w in wps]
    except Exception:
        return []


def _resolve_vertex(text: str) -> str | None:
    """발화 → 목적지 vertex name. 별칭 우선, 없으면 (goto 패턴 + vertex 이름).

    별칭은 goto 패턴 없이도 매칭 (구절 자체가 이동 의도 — "밖으로 나가").
    """
    t = text.strip()
    if not t:
        return None

    # 1) 별칭 — 더 긴 구절 먼저 (구체 우선).
    for phrase in sorted(_VERTEX_ALIASES, key=len, reverse=True):
        if phrase in t:
            return _VERTEX_ALIASES[phrase]

    # 2) goto 패턴 + vertex 이름 (더 긴 이름 먼저).
    if not any(p in t for p in _GOTO_PATTERNS):
        return None
    names = sorted(_load_vertex_names(), key=len, reverse=True)
    for name in names:
        if name and name in t:
            return name
    # 2b) 정식 이름 매칭 실패 → STT 변형 alias fallback (goto 패턴은 이미 통과).
    for variant in sorted(_VERTEX_NAME_ALIASES, key=len, reverse=True):
        if variant in t:
            return _VERTEX_NAME_ALIASES[variant]
    return None


def _resolve_then_mode(text: str) -> str:
    """발화에 도착 후 전환 모드 키워드가 있으면 그 모드 라벨, 없으면 빈 문자열."""
    t = text.strip()
    for keyword, mode in _THEN_MODE_KEYWORDS.items():
        if keyword in t:
            return mode
    return ""


class GotoVertexHandler(IntentHandler):
    name: ClassVar[str] = "goto_vertex"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        vname = _resolve_vertex(req.text)
        if vname is None:
            return None
        return GotoVertex(name=vname, then_mode=_resolve_then_mode(req.text))
