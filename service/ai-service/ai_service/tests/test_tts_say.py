"""POST /api/tts/say — 고정 멘트 edge_tts 합성 endpoint 단위테스트."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from ai_service.hub import app
    return TestClient(app)


async def _fake_stream(text: str):
    yield b"FAKE_MP3_HEADER"
    yield b"FAKE_MP3_BODY"


def test_tts_say_returns_audio_mpeg(client):
    with patch("ai_service.edge_tts_synth.synthesize_edge_mp3_stream", side_effect=_fake_stream):
        r = client.post("/api/tts/say", json={"text": "선생님 찾았습니다"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("audio/mpeg")
        assert b"FAKE_MP3" in r.content


def test_tts_say_empty_text_still_200(client):
    """edge_tts 가 빈 text 도 fallback 멘트로 치환 — endpoint 자체는 200."""
    with patch("ai_service.edge_tts_synth.synthesize_edge_mp3_stream", side_effect=_fake_stream):
        r = client.post("/api/tts/say", json={"text": ""})
        assert r.status_code == 200
