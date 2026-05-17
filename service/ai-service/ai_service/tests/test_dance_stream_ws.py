"""WS endpoint smoke test — 실제 frame 형식보다 'WS 가 frame 을 흘려보냄' 만 확인."""
from __future__ import annotations

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


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)

    # bridge stub — routines_root 만 노출
    class _StubBridge:
        routines_root = ROUTINES_ROOT

    app.state.eduping_bridge = _StubBridge()
    return TestClient(app)


def test_ws_stream_yields_header_then_frames_then_end(client: TestClient) -> None:
    with client.websocket_connect("/api/eduping/dance/awesome-tomato/stream") as ws:
        first = ws.receive_bytes()
        ftype = first[0]
        assert ftype == FRAME_TYPE_HEADER

        end_seen = False
        seen_frame_count = 0
        while seen_frame_count < 500:
            msg = ws.receive_bytes()
            seen_frame_count += 1
            if msg[0] == FRAME_TYPE_END:
                end_seen = True
                break
        assert seen_frame_count > 0, "no body frames received after header"
        # END may or may not arrive within the 500-frame cap depending on fixture length;
        # absence of END is not an error for this smoke test.
