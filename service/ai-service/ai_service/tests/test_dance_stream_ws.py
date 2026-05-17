"""WS endpoint smoke test — bidirectional 채널이 play 컨트롤을 받아 frame 을 흘려보내는지 확인."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from control_service.eduping.dance_stream import (
    FRAME_TYPE_END,
    FRAME_TYPE_HEADER,
)
from control_service.eduping.router import router


def _find_repo_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").exists():
            return p
    raise RuntimeError(f"repo root (pyproject.toml) not found from {start}")


REPO_ROOT = _find_repo_root(Path(__file__).resolve())
ROUTINES_ROOT = REPO_ROOT / "shared"

pytestmark = pytest.mark.skipif(
    not (ROUTINES_ROOT / "openarm_dance" / "awesome-tomato" / "song.mp3").exists(),
    reason="fixture dance 없음",
)


class _StubFollower:
    joint_names: list[str] = []
    positions: list[float] = []


class _StubBridge:
    routines_root = ROUTINES_ROOT
    _lock = threading.Lock()
    _follower = _StubFollower()

    def play_routine(self, *args, **kwargs):  # noqa: D401
        return {"ok": True}

    def return_to_home(self, *args, **kwargs):
        return {"ok": True, "stubbed": True}


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.eduping_bridge = _StubBridge()
    return TestClient(app)


def test_ws_stream_play_yields_header_then_frames(client: TestClient) -> None:
    with client.websocket_connect("/api/eduping/dance/stream") as ws:
        ws.send_text(json.dumps({"type": "play", "slug": "awesome-tomato"}))
        first = ws.receive_bytes()
        assert first[0] == FRAME_TYPE_HEADER

        seen = 0
        while seen < 500:
            msg = ws.receive_bytes()
            seen += 1
            if msg[0] == FRAME_TYPE_END:
                break
        assert seen > 0, "no body frames received after header"
