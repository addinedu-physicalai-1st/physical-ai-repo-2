"""GotoVertexHandler — gogoping 전용 'X로 가' vertex routing."""
from unittest.mock import patch

from ai_service.hub import GotoVertex
from ai_service.intents.gogoping.goto_vertex import GotoVertexHandler
from ai_service.tests.intents.conftest import make_ctx, make_req


async def test_goto_vertex_matches() -> None:
    text = "교실로 가"
    with patch(
        "ai_service.intents.gogoping.goto_vertex._load_vertex_names"
    ) as m:
        m.return_value = ["교실", "운동장"]
        r = await GotoVertexHandler().try_handle(
            make_req(text, robot="gogoping"), make_ctx(text, robot="gogoping")
        )
    assert r == GotoVertex(name="교실")


async def test_goto_vertex_no_match() -> None:
    text = "안녕"
    with patch(
        "ai_service.intents.gogoping.goto_vertex._load_vertex_names"
    ) as m:
        m.return_value = ["교실"]
        r = await GotoVertexHandler().try_handle(
            make_req(text, robot="gogoping"), make_ctx(text, robot="gogoping")
        )
    assert r is None


import pytest


# 사용자 핵심 발화 + STT 오인식 변형 → 모두 놀이방 라우팅.
@pytest.mark.parametrize(
    "text,expected",
    [
        ("놀이방으로 가자", GotoVertex(name="놀이방")),
        ("놀이방으로 이동해줘", GotoVertex(name="놀이방")),
        ("놀이방으로 가서 자장가틀어줘", GotoVertex(name="놀이방", then_mode="자장가")),
        ("놀이방 가서 재워줘", GotoVertex(name="놀이방", then_mode="자장가")),
        ("놀이반으로 가자", GotoVertex(name="놀이방")),       # STT 오인식
        ("노리방으로 이동", GotoVertex(name="놀이방")),       # STT 오인식
        ("놀이 방으로 가줘", GotoVertex(name="놀이방")),      # 띄어쓰기
        ("수면시로 가", GotoVertex(name="수면실")),          # STT 오인식
    ],
)
async def test_goto_vertex_user_sentences(text: str, expected: GotoVertex) -> None:
    names = ["놀이방", "수면실", "충전소", "복도", "출입구"]
    with patch(
        "ai_service.intents.gogoping.goto_vertex._load_vertex_names",
        return_value=names,
    ):
        r = await GotoVertexHandler().try_handle(
            make_req(text, robot="gogoping"), make_ctx(text, robot="gogoping")
        )
    assert r == expected
