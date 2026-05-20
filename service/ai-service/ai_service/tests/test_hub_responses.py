"""AI Hub HTTP 응답 — Ollama 없이 검증 가능한 경로 + Edge TTS 계약.

`/voice/intent` 는 규칙 기반(정지·인사·빠른 응답·모드 키워드) 후 필요 시에만 `generate_chat`(Ollama) 호출.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import ai_service.hub as hub_mod
from ai_service.hub import app

client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_post_mode_valid() -> None:
    r = client.post("/mode", json={"robot": "gogoping", "mode": "대기"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["robot"] == "gogoping"
    assert body["mode"] == "대기"


def test_post_mode_invalid() -> None:
    r = client.post("/mode", json={"robot": "gogoping", "mode": "없는모드"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


@pytest.mark.parametrize("text", ["그만해", "멈춰", "정지", "스톱"])
def test_voice_intent_stop(text: str) -> None:
    r = client.post("/voice/intent", json={"text": text, "robot": "gogoping"})
    assert r.status_code == 200
    assert r.json() == {"kind": "sub_command", "action": "stop"}


def test_voice_intent_invalid_robot_rejected() -> None:
    r = client.post("/voice/intent", json={"text": "안녕", "robot": "not-a-robot"})
    assert r.status_code == 422


def test_voice_intent_greeting_chat_shape() -> None:
    r = client.post("/voice/intent", json={"text": "안녕", "robot": "gogoping"})
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "chat"
    assert "reply" in data and data["reply"]
    assert data.get("emotion") == "hello"


def test_voice_intent_name_question_uses_chat_path() -> None:
    with patch("ai_service.hub.generate_chat", new_callable=AsyncMock) as m:
        m.return_value = {"reply": "고고핑이에요! 반가워요.", "emotion": "happy"}
        r = client.post("/voice/intent", json={"text": "너 이름이 뭐야?", "robot": "gogoping"})
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "chat"
    assert "고고핑" in data["reply"]
    assert data.get("emotion") == "happy"
    m.assert_awaited_once()


def test_voice_intent_schedule_skips_llm() -> None:
    with patch("ai_service.hub.generate_chat", new_callable=AsyncMock) as m:
        r = client.post(
            "/voice/intent",
            json={"text": "일과표 알려줘", "robot": "gogoping"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "chat"
    assert "등원" in data["reply"] or "점심" in data["reply"] or "일과표" in data["reply"]
    m.assert_not_called()


def test_voice_intent_llm_timeout_returns_teacher_line() -> None:
    async def slow_chat(*args: object, **kwargs: object) -> dict[str, str]:
        await asyncio.sleep(0.3)
        return {"reply": "늦게 온 답", "emotion": "happy"}

    with patch.object(hub_mod.ai_settings, "voice_chat_llm_max_wait_s", 0.1):
        with patch("ai_service.hub.build_chat_context", new_callable=AsyncMock) as _ctx:
            _ctx.return_value = {}
            with patch(
                "ai_service.hub.fetch_registered_children_labels",
                new_callable=AsyncMock,
            ) as _ro:
                _ro.return_value = None
                with patch("ai_service.hub.generate_chat", side_effect=slow_chat):
                    r = client.post(
                        "/voice/intent",
                        json={"text": "트럼프 관세 정책 어떻게 생각해", "robot": "gogoping"},
                    )
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "chat"
    assert "모르겠" in data["reply"] and "선생님" in data["reply"]
    assert data.get("emotion") == "basic"


def test_voice_intent_mode_keyword_eduping() -> None:
    r = client.post(
        "/voice/intent",
        json={"text": "지금부터 율동 모드로 해줘", "robot": "eduping"},
    )
    assert r.status_code == 200
    assert r.json() == {"kind": "mode_change", "mode": "율동"}


def test_voice_intent_emotion_demo_angry_skips_llm() -> None:
    with patch("ai_service.hub.generate_chat", new_callable=AsyncMock) as m:
        r = client.post(
            "/voice/intent",
            json={"text": "화내봐!", "robot": "gogoping"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "chat"
    assert data["emotion"] == "angry"
    assert "화났" in data["reply"]
    m.assert_not_called()


def test_voice_intent_emotion_demo_sad() -> None:
    r = client.post(
        "/voice/intent",
        json={"text": "슬퍼봐", "robot": "gogoping"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "chat"
    assert data["emotion"] == "sad"
    assert "슬퍼" in data["reply"] or "슬" in data["reply"]


def test_voice_intent_lunch_fast_path_mocked_menu() -> None:
    with patch("ai_service.capabilities.db_menu.get_menu_fast", new_callable=AsyncMock) as m:
        m.return_value = "오늘 점심은 단위테스트밥이 나온대요!"
        r = client.post(
            "/voice/intent",
            json={"text": "오늘 점심 메뉴 뭐야?", "robot": "gogoping"},
        )
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "chat"
    assert "단위테스트밥" in data["reply"]
    assert data.get("emotion") == "happy"


def test_voice_intent_yesterday_menu_passes_relative() -> None:
    with patch("ai_service.capabilities.db_menu.get_menu_fast", new_callable=AsyncMock) as m:
        m.return_value = "어제 점심은 테스트!"
        r = client.post(
            "/voice/intent",
            json={"text": "어제 메뉴", "robot": "gogoping"},
        )
    assert r.status_code == 200
    assert r.json()["kind"] == "chat"
    m.assert_awaited_once()
    assert m.await_args.kwargs.get("relative") == "yesterday"


def test_voice_intent_day_before_yesterday_menu_passes_relative() -> None:
    with patch("ai_service.capabilities.db_menu.get_menu_fast", new_callable=AsyncMock) as m:
        m.return_value = "그저께 점심은 테스트!"
        r = client.post(
            "/voice/intent",
            json={"text": "엊그제 급식", "robot": "gogoping"},
        )
    assert r.status_code == 200
    assert r.json()["kind"] == "chat"
    m.assert_awaited_once()
    assert m.await_args.kwargs.get("relative") == "day_before_yesterday"


def test_voice_tts_empty_text() -> None:
    r = client.get("/voice/tts", params={"text": "  "})
    assert r.status_code == 400


def test_voice_tts_edge_returns_mpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream(_text: str):
        yield b"\xff" * 160
        yield b"\xff" * 160

    monkeypatch.setattr(hub_mod, "synthesize_edge_mp3_stream", fake_stream)
    r = client.get("/voice/tts", params={"text": "테스트"})
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("audio/mpeg")
    assert len(r.content) == 320
