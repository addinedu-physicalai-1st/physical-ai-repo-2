"""로봇별 프롬프트 레지스트리.

로봇별 시스템 프롬프트·few-shot 은 각 sibling 모듈
(`eduping.py`, `gogoping.py`, `noriarm.py`) 에 둔다.
앞으로 톤·예시·매칭 규칙이 로봇마다 갈라져도 이 디렉토리 안에서만 수정한다.
"""
from types import ModuleType

from ai_service.prompts import eduping, gogoping, noriarm
from ai_service.prompts.shared_chat_guardrails import (
    CHILD_SAFE_CURRENT_EVENTS_BLOCK,
    honesty_nonsense_block,
)

_REGISTRY: dict[str, ModuleType] = {
    "eduping": eduping,
    "gogoping": gogoping,
    "noriarm": noriarm,
}


def _module(robot: str) -> ModuleType:
    try:
        return _REGISTRY[robot]
    except KeyError as exc:
        raise KeyError(f"unknown robot: {robot}") from exc


def display_name(robot: str) -> str:
    return _module(robot).DISPLAY_NAME


def chat_system(robot: str, *, context_block: str, emotions_block: str) -> str:
    name = display_name(robot)
    return _module(robot).CHAT_SYSTEM.format(
        robot_name=name,
        child_safe_current_events_block=CHILD_SAFE_CURRENT_EVENTS_BLOCK,
        honesty_nonsense_block=honesty_nonsense_block(name),
        context_block=context_block,
        emotions_block=emotions_block,
    )


def chat_few_shot(robot: str) -> list[tuple[str, dict[str, str]]]:
    name = display_name(robot)
    return [
        (
            user_msg,
            {"reply": obj["reply"].format(robot_name=name), "emotion": obj["emotion"]},
        )
        for user_msg, obj in _module(robot).CHAT_FEW_SHOT
    ]
