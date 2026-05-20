"""로봇별 intent 파이프라인 — 순서 = 우선순위."""
from ai_service.intents.base import (
    IntentContext,
    IntentHandler,
    IntentResponse,
    now_kst,
)
from ai_service.intents.common.emotion_demo import EmotionDemoHandler
from ai_service.intents.common.gender import GenderHandler
from ai_service.intents.common.hello import HelloHandler
from ai_service.intents.common.menu import MenuHandler
from ai_service.intents.common.mode_change import ModeChangeHandler
from ai_service.intents.common.stop import StopHandler

PIPELINES: dict[str, list[IntentHandler]] = {
    "eduping": [
        StopHandler(),
        MenuHandler(),
        HelloHandler(),
        GenderHandler(),
        ModeChangeHandler(),
        EmotionDemoHandler(),
    ],
    "gogoping": [
        StopHandler(),
        MenuHandler(),
        HelloHandler(),
        GenderHandler(),
        ModeChangeHandler(),
        EmotionDemoHandler(),
    ],
    "noriarm": [
        StopHandler(),
        MenuHandler(),
        HelloHandler(),
        GenderHandler(),
        ModeChangeHandler(),
        EmotionDemoHandler(),
    ],
}

__all__ = ["IntentContext", "IntentHandler", "IntentResponse", "PIPELINES", "now_kst"]
