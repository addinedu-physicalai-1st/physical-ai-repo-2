"""EmotionDemoHandler — '화내봐' '슬퍼봐' 등 감정 연기 요청."""
from ai_service.hub import Chat
from ai_service.intents.common.emotion_demo import EmotionDemoHandler
from ai_service.tests.intents.conftest import make_ctx, make_req


async def test_emotion_demo_angry() -> None:
    r = await EmotionDemoHandler().try_handle(
        make_req("화내봐!", robot="gogoping"),
        make_ctx("화내봐!", robot="gogoping"),
    )
    assert isinstance(r, Chat)
    assert r.emotion == "angry"
    assert "화났" in r.reply


async def test_emotion_demo_sad() -> None:
    r = await EmotionDemoHandler().try_handle(
        make_req("슬퍼봐", robot="gogoping"),
        make_ctx("슬퍼봐", robot="gogoping"),
    )
    assert isinstance(r, Chat)
    assert r.emotion == "sad"


async def test_emotion_demo_passes_through_long_unrelated() -> None:
    text = "오늘 날씨가 어떤지 자세히 알려줄 수 있을까?"
    r = await EmotionDemoHandler().try_handle(make_req(text), make_ctx(text))
    assert r is None
