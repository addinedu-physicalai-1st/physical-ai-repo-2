"""로봇별 intent 파이프라인 — 순서 = 우선순위."""
from ai_service.intents.base import (
    IntentContext,
    IntentHandler,
    IntentResponse,
    now_kst,
)
from ai_service.intents.common.gender import GenderHandler
from ai_service.intents.common.hello import HelloHandler
from ai_service.intents.common.menu import MenuHandler
from ai_service.intents.common.stop import StopHandler

PIPELINES: dict[str, list[IntentHandler]] = {
    "eduping": [StopHandler(), MenuHandler(), HelloHandler(), GenderHandler()],
    "gogoping": [StopHandler(), MenuHandler(), HelloHandler(), GenderHandler()],
    "noriarm": [StopHandler(), MenuHandler(), HelloHandler(), GenderHandler()],
}

__all__ = ["IntentContext", "IntentHandler", "IntentResponse", "PIPELINES", "now_kst"]
