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
