"""핸들러 unit test 용 공용 fixture / helper."""
from __future__ import annotations

from ai_service.hub import IntentRequest
from ai_service.intents import IntentContext, now_kst


def make_req(text: str, robot: str = "gogoping", class_roster: list[str] | None = None) -> IntentRequest:
    return IntentRequest(text=text, robot=robot, class_roster=class_roster or [])


def make_ctx(text: str, robot: str = "gogoping", class_roster: list[str] | None = None) -> IntentContext:
    req = make_req(text, robot=robot, class_roster=class_roster)
    return IntentContext(now=now_kst(), req=req)
