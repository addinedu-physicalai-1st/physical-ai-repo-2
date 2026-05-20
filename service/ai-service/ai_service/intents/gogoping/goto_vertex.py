"""gogoping 전용 — 'X로 가' / 'X에 가' vertex routing."""
from __future__ import annotations

from typing import ClassVar

from ai_service.hub import GotoVertex, IntentRequest
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse

_GOTO_PATTERNS = (
    "로 가", "로 이동", "에 가", "로 갑", "에 갑", "로 갈",
    "에 갈", "로 향", "로 와", "에 와", " 가자", " 가줘", " 가",
)


def _load_vertex_names() -> list[str]:
    """waypoints.yaml 의 vertex name 목록. yaml read 는 가벼움 (< 1ms)."""
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
    if not any(p in t for p in _GOTO_PATTERNS):
        return None
    names = sorted(_load_vertex_names(), key=len, reverse=True)
    for name in names:
        if name and name in t:
            return name
    return None


class GotoVertexHandler(IntentHandler):
    name: ClassVar[str] = "goto_vertex"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        vname = _try_goto_vertex(req.text)
        if vname is None:
            return None
        return GotoVertex(name=vname)
