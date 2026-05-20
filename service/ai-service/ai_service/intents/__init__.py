"""로봇별 intent 파이프라인 — 순서 = 우선순위."""
from ai_service.intents.base import (
    IntentContext,
    IntentHandler,
    IntentResponse,
    _now_kst,
)

PIPELINES: dict[str, list[IntentHandler]] = {
    "eduping": [],
    "gogoping": [],
    "noriarm": [],
}

__all__ = ["IntentContext", "IntentHandler", "IntentResponse", "PIPELINES", "_now_kst"]
