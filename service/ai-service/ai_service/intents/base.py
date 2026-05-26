"""IntentHandler ABC + 요청별 공유 컨텍스트."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import ClassVar

from ai_service.hub import (
    Chat,
    ConfirmNo,
    ConfirmYes,
    GotoVertex,
    IntentRequest,
    ModeChange,
    RhythmPlay,
    RhythmStop,
    StoreItem,
    SubCommand,
)

IntentResponse = (
    ModeChange
    | SubCommand
    | GotoVertex
    | Chat
    | RhythmPlay
    | RhythmStop
    | ConfirmYes
    | ConfirmNo
    | StoreItem
)


def now_kst() -> datetime:
    return datetime.utcnow() + timedelta(hours=9)


@dataclass
class IntentContext:
    """같은 요청 내 핸들러들이 공유하는 mutable bag.

    - `now`: KST 현재시각 (요청 진입 시 고정).
    - `req`: 원본 요청 (편의용 참조).
    - `_roster`, `_chat_ctx`: lazy-loaded, ChatFallback 등이 채움.
    """
    now: datetime
    req: IntentRequest
    _roster: str | None = field(default=None, init=False, repr=False)
    _chat_ctx: dict[str, str] | None = field(default=None, init=False, repr=False)


class IntentHandler(ABC):
    name: ClassVar[str]

    @abstractmethod
    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        """매치되면 IntentResponse, 아니면 None (다음 핸들러로 패스)."""
