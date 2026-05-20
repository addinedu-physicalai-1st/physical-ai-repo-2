"""WakeNameHandler — 로봇 이름만 외친 발화 → 친근한 ack."""
import pytest

from ai_service.hub import Chat
from ai_service.intents.common.wake_name import WakeNameHandler
from ai_service.tests.intents.conftest import make_ctx, make_req


@pytest.mark.parametrize(
    "text,robot,expected_name",
    [
        ("에듀핑", "eduping", "에듀핑"),
        ("에듀핑.", "eduping", "에듀핑"),
        ("에듀핑!", "eduping", "에듀핑"),
        ("에듀핀", "eduping", "에듀핑"),  # alias
        ("고고핑", "gogoping", "고고핑"),
        ("고고핀", "gogoping", "고고핑"),
        ("노리암", "noriarm", "노리암"),
        ("놀이암", "noriarm", "노리암"),
        ("EduPing", "eduping", "에듀핑"),  # case insensitive displayName
        ("  에듀핑  ", "eduping", "에듀핑"),  # whitespace tolerated
    ],
)
async def test_wake_name_matches(text: str, robot: str, expected_name: str) -> None:
    r = await WakeNameHandler().try_handle(
        make_req(text, robot=robot), make_ctx(text, robot=robot)
    )
    assert isinstance(r, Chat)
    assert expected_name in r.reply
    assert r.emotion == "hello"


@pytest.mark.parametrize(
    "text,robot",
    [
        ("에듀핑 안녕", "eduping"),  # name + 추가 발화 → 통과
        ("에듀핑아", "eduping"),  # 호격 조사 → 통과 (LLM 처리)
        ("에듀핑이 좋아", "eduping"),  # 평서문 → 통과
        ("고고핑", "eduping"),  # 다른 로봇 이름 → 통과
        ("점심 메뉴", "eduping"),  # 무관한 발화 → 통과
    ],
)
async def test_wake_name_passes_through(text: str, robot: str) -> None:
    r = await WakeNameHandler().try_handle(
        make_req(text, robot=robot), make_ctx(text, robot=robot)
    )
    assert r is None
