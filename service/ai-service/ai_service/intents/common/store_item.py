"""가게놀이 음식 요청 발화 → StoreItem. noriarm 전용.

"딸기 줘", "포도 주세요", "키위 가져와", "strawberry" 등에서 5종 과일 id 추출.
robot-web 이 가게놀이 모드일 때만 serve 로 연결 (다른 모드면 무시) — 모드 가드는
클라이언트 책임. 여기선 item 단어가 있으면 StoreItem 반환.

keyword 매칭 (LLM 불필요) — 5종 고정 task set 이라 빠르고 결정적.
"""
from __future__ import annotations

from typing import ClassVar

from ai_service.hub import IntentRequest, StoreItem
from ai_service.intents.base import IntentContext, IntentHandler, IntentResponse

# 한국어/영어 표면형 → 영어 item id. config/items.yaml 의 5종과 1:1.
# 긴 키 우선 매칭 (substring 충돌 방지 — 현재 5종은 충돌 없지만 안전).
_ITEM_MAP: dict[str, str] = {
    "딸기": "strawberry",
    "strawberry": "strawberry",
    "브로콜리": "broccoli",
    "broccoli": "broccoli",
    "포도": "grape",
    "grape": "grape",
    "키위": "kiwi",
    "kiwi": "kiwi",
    "파인애플": "pineapple",
    "pineapple": "pineapple",
}


def _extract_item(text: str) -> str | None:
    lower = text.lower().strip()
    # 긴 표면형 우선 (예: "파인애플" 이 "애플" 류와 충돌하지 않게).
    for surface in sorted(_ITEM_MAP, key=len, reverse=True):
        if surface in lower:
            return _ITEM_MAP[surface]
    return None


class StoreItemHandler(IntentHandler):
    name: ClassVar[str] = "store_item"

    async def try_handle(
        self, req: IntentRequest, ctx: IntentContext
    ) -> IntentResponse | None:
        item = _extract_item(req.text)
        if item is not None:
            return StoreItem(item=item)
        return None
