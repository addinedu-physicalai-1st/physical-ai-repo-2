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
from ai_service.intents.common.start import StartHandler
from ai_service.intents.common.stop import StopHandler
from ai_service.intents.common.whereabouts import WhereaboutsHandler
from ai_service.intents.eduping.confirm import ConfirmHandler
from ai_service.intents.eduping.rhythm import RhythmPlayHandler, RhythmStopHandler
from ai_service.intents.gogoping.goto_vertex import GotoVertexHandler
from ai_service.intents.gogoping.return_ import ReturnHandler

# 율동 모드 안에서는 곡 선택/재생/정지/모드전환만 허용 — 잡담·메뉴·인사 등
# 일반 핸들러는 비활성. ChatFallback 도 없음 (매치 실패 시 ignored 반환).
_EDUPING_RHYTHM_PIPELINE: list[IntentHandler] = [
    ConfirmHandler(),
    RhythmStopHandler(),
    StopHandler(),
    StartHandler(),
    ModeChangeHandler(),
    RhythmPlayHandler(),
]

PIPELINES: dict[str, list[IntentHandler]] = {
    "eduping": [
        ConfirmHandler(),
        RhythmStopHandler(),
        StopHandler(),
        StartHandler(),
        MenuHandler(),
        HelloHandler(),
        GenderHandler(),
        ModeChangeHandler(),
        EmotionDemoHandler(),
        ScheduleHandler(),
        WhereaboutsHandler(),
        ReportHandler(),
        AttendanceHandler(),
        RhythmPlayHandler(),
        ChatFallbackHandler(),
    ],
    "gogoping": [
        StopHandler(),
        StartHandler(),
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
        StartHandler(),
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


def get_pipeline(robot: str, mode: str | None) -> list[IntentHandler]:
    if robot == "eduping" and mode == "율동":
        return _EDUPING_RHYTHM_PIPELINE
    return PIPELINES.get(robot, [])


__all__ = [
    "IntentContext",
    "IntentHandler",
    "IntentResponse",
    "PIPELINES",
    "get_pipeline",
    "now_kst",
]
