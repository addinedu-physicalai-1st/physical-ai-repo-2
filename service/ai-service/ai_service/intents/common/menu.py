"""점심·메뉴·급식 질문 → DB pgvector 조회로 빠른 응답."""
from __future__ import annotations

import re
from typing import ClassVar

from ai_service.capabilities import db_menu
from ai_service.hub import Chat, IntentRequest
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse

_MENU_TOKENS = ("점심", "메뉴", "급식")
_MENU_DATE_MARKERS = (
    "오늘", "내일", "어제", "그저께", "엊그제", "모레", "글피", "그끄저께",
    "하루", "이틀", "사흘", "나흘", "닷새",
    "뒤", "후", "전", "전에", "이전", "만에", "뭐",
)


class MenuHandler(IntentHandler):
    name: ClassVar[str] = "menu"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        text = req.text.strip()
        has_token = any(kw in text for kw in _MENU_TOKENS)
        if not has_token:
            return None
        has_date_marker = any(w in text for w in _MENU_DATE_MARKERS) or bool(
            re.search(r"\d+\s*일", text)
        )
        if not has_date_marker:
            return None

        day, relative = db_menu.parse_menu_query_calendar_day(text, ctx.now)
        menu_text = await db_menu.get_menu_fast(day, relative=relative)
        return Chat(reply=menu_text, emotion="happy")
