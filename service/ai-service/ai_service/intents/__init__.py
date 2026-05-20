"""로봇별 intent 파이프라인 — 순서 = 우선순위."""
from ai_service.intents.base import (
    IntentContext,
    IntentHandler,
    IntentResponse,
    now_kst,
)
from ai_service.intents.common.attendance import AttendanceHandler
from ai_service.intents.common.chat_fallback import ChatFallbackHandler
from ai_service.intents.common.emotion_demo import EmotionDemoHandler
from ai_service.intents.common.gender import GenderHandler
from ai_service.intents.common.hello import HelloHandler
from ai_service.intents.common.menu import MenuHandler
from ai_service.intents.common.mode_change import ModeChangeHandler
from ai_service.intents.common.report import ReportHandler
from ai_service.intents.common.schedule import ScheduleHandler
from ai_service.intents.common.stop import StopHandler
from ai_service.intents.common.whereabouts import WhereaboutsHandler
from ai_service.intents.gogoping.goto_vertex import GotoVertexHandler
from ai_service.intents.gogoping.return_ import ReturnHandler

PIPELINES: dict[str, list[IntentHandler]] = {
    "eduping": [
        StopHandler(),
        MenuHandler(),
        HelloHandler(),
        GenderHandler(),
        ModeChangeHandler(),
        EmotionDemoHandler(),
        ScheduleHandler(),
        WhereaboutsHandler(),
        ReportHandler(),
        AttendanceHandler(),
        ChatFallbackHandler(),
    ],
    "gogoping": [
        StopHandler(),
        ReturnHandler(),
        GotoVertexHandler(),
        MenuHandler(),
        HelloHandler(),
        GenderHandler(),
        ModeChangeHandler(),
        EmotionDemoHandler(),
        ScheduleHandler(),
        WhereaboutsHandler(),
        ReportHandler(),
        AttendanceHandler(),
        ChatFallbackHandler(),
    ],
    "noriarm": [
        StopHandler(),
        MenuHandler(),
        HelloHandler(),
        GenderHandler(),
        ModeChangeHandler(),
        EmotionDemoHandler(),
        ScheduleHandler(),
        WhereaboutsHandler(),
        ReportHandler(),
        AttendanceHandler(),
        ChatFallbackHandler(),
    ],
}

__all__ = ["IntentContext", "IntentHandler", "IntentResponse", "PIPELINES", "now_kst"]
