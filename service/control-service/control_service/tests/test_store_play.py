"""가게놀이 long-lived session API 단위 테스트.

RunnerProcess 를 mock 해서 실제 서브프로세스 없이 동작 검증.
세션 lifecycle: create → start → serve (× N) → delete.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from control_service.noriarm.store_play import (
    StorePlaySession,
    _store,
    router,
)


# ── Minimal FastAPI app (DB 없음, noriarm router 만) ──────────────────────────
from fastapi import FastAPI

_app = FastAPI()
_app.include_router(router, prefix="/api/noriarm")


@pytest_asyncio.fixture(autouse=True)
async def clear_store():
    """각 테스트 전후로 세션 스토어 비우기."""
    _store._sessions.clear()
    yield
    _store._sessions.clear()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=_app), base_url="http://test"
    ) as ac:
        yield ac


def _make_mock_runner(*, ready: bool = True, task_done: bool = True) -> MagicMock:
    runner = MagicMock()
    runner.start = AsyncMock()
    runner.wait_ready = AsyncMock(return_value=ready)
    runner.send_start = AsyncMock()
    runner.send_prompt = AsyncMock()
    runner.wait_task_done = AsyncMock(return_value=task_done)
    runner.send_abort = AsyncMock()
    runner.send_quit = AsyncMock()
    runner.terminate = AsyncMock()
    runner.wait_exit = AsyncMock(return_value=0)
    runner.alive = True
    return runner


# ──────────────────────────────────────────────────────── create / start


@pytest.mark.anyio
async def test_create_session_ok(client: AsyncClient) -> None:
    with patch(
        "control_service.noriarm.store_play.RunnerProcess",
        return_value=_make_mock_runner(),
    ):
        r = await client.post(
            "/api/noriarm/games/store-play/sessions",
            json={"target": "real"},
        )
    assert r.status_code == 200, r.text
    data = r.json()
    assert "session_id" in data
    assert data["status"] == "loading"


@pytest.mark.anyio
async def test_start_play_ok(client: AsyncClient) -> None:
    runner = _make_mock_runner(ready=True)
    with patch("control_service.noriarm.store_play.RunnerProcess", return_value=runner):
        r1 = await client.post(
            "/api/noriarm/games/store-play/sessions", json={"target": "real"},
        )
    sid = r1.json()["session_id"]

    r2 = await client.post(f"/api/noriarm/games/store-play/sessions/{sid}/start")
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "idle"
    runner.send_start.assert_awaited_once()


@pytest.mark.anyio
async def test_start_play_not_ready(client: AsyncClient) -> None:
    runner = _make_mock_runner(ready=False)
    with patch("control_service.noriarm.store_play.RunnerProcess", return_value=runner):
        r1 = await client.post(
            "/api/noriarm/games/store-play/sessions", json={"target": "real"},
        )
    sid = r1.json()["session_id"]
    r2 = await client.post(f"/api/noriarm/games/store-play/sessions/{sid}/start")
    assert r2.status_code == 500


# ──────────────────────────────────────────────────────── serve


@pytest.mark.anyio
async def test_serve_requires_idle(client: AsyncClient) -> None:
    """create 직후 (loading) 상태 — serve 호출 불가."""
    runner = _make_mock_runner()
    with patch("control_service.noriarm.store_play.RunnerProcess", return_value=runner):
        r1 = await client.post(
            "/api/noriarm/games/store-play/sessions", json={"target": "real"},
        )
    sid = r1.json()["session_id"]
    # start 안 부른 채로 serve 시도 — 409
    r2 = await client.post(
        f"/api/noriarm/games/store-play/sessions/{sid}/serve",
        json={"prompt": "give me strawberry"},
    )
    assert r2.status_code == 409


@pytest.mark.anyio
async def test_serve_ok_after_start(client: AsyncClient) -> None:
    runner = _make_mock_runner()
    with patch("control_service.noriarm.store_play.RunnerProcess", return_value=runner):
        r1 = await client.post(
            "/api/noriarm/games/store-play/sessions", json={"target": "real"},
        )
        sid = r1.json()["session_id"]
        await client.post(f"/api/noriarm/games/store-play/sessions/{sid}/start")

        r2 = await client.post(
            f"/api/noriarm/games/store-play/sessions/{sid}/serve",
            json={"prompt": "give me kiwi"},
        )
        # _serve_and_emit 가 background task 라 event loop 한 cycle 돌려야 send_prompt 호출.
        await asyncio.sleep(0.05)
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "serving"
    runner.send_prompt.assert_awaited_with("give me kiwi")


@pytest.mark.anyio
async def test_serve_multiple_tasks(client: AsyncClient) -> None:
    """idle → serve(strawberry) → done → idle → serve(grape) → done. 같은 session 재사용."""
    runner = _make_mock_runner(task_done=True)
    with patch("control_service.noriarm.store_play.RunnerProcess", return_value=runner):
        r1 = await client.post(
            "/api/noriarm/games/store-play/sessions", json={"target": "real"},
        )
        sid = r1.json()["session_id"]
        await client.post(f"/api/noriarm/games/store-play/sessions/{sid}/start")

        # 1차 serve
        r2 = await client.post(
            f"/api/noriarm/games/store-play/sessions/{sid}/serve",
            json={"prompt": "give me strawberry"},
        )
        assert r2.status_code == 200
        # _serve_and_emit 가 완료될 때까지 기다림 — idle 복귀.
        for _ in range(50):
            session = _store.get(sid)
            assert session is not None
            if session.status == "idle":
                break
            await asyncio.sleep(0.01)
        assert session.status == "idle"

        # 2차 serve — 새 prompt
        r3 = await client.post(
            f"/api/noriarm/games/store-play/sessions/{sid}/serve",
            json={"prompt": "give me grape"},
        )
        assert r3.status_code == 200
        # 두 번째 _serve_and_emit 도 background — send_prompt 호출까지 yield.
        await asyncio.sleep(0.05)
    assert runner.send_prompt.await_count == 2


# ──────────────────────────────────────────────────────── abort


@pytest.mark.anyio
async def test_abort_during_serving(client: AsyncClient) -> None:
    runner = _make_mock_runner()
    with patch("control_service.noriarm.store_play.RunnerProcess", return_value=runner):
        r1 = await client.post(
            "/api/noriarm/games/store-play/sessions", json={"target": "real"},
        )
        sid = r1.json()["session_id"]
        await client.post(f"/api/noriarm/games/store-play/sessions/{sid}/start")
        await client.post(
            f"/api/noriarm/games/store-play/sessions/{sid}/serve",
            json={"prompt": "give me strawberry"},
        )
        r_abort = await client.post(f"/api/noriarm/games/store-play/sessions/{sid}/abort")
    assert r_abort.status_code == 200
    runner.send_abort.assert_awaited()


# ──────────────────────────────────────────────────────── delete


@pytest.mark.anyio
async def test_delete_unknown_session(client: AsyncClient) -> None:
    r = await client.delete("/api/noriarm/games/store-play/sessions/doesnotexist")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.anyio
async def test_delete_session_quits_cleanly(client: AsyncClient) -> None:
    """DELETE 는 send_quit 먼저, terminate 는 폴백."""
    runner = _make_mock_runner()
    with patch("control_service.noriarm.store_play.RunnerProcess", return_value=runner):
        r1 = await client.post(
            "/api/noriarm/games/store-play/sessions", json={"target": "real"},
        )
        sid = r1.json()["session_id"]
        await client.post(f"/api/noriarm/games/store-play/sessions/{sid}/start")
        r2 = await client.delete(f"/api/noriarm/games/store-play/sessions/{sid}")
    assert r2.status_code == 200
    runner.send_quit.assert_awaited_once()
    # wait_exit 가 즉시 (0 return) 반환 → terminate 호출 안 됨.
    runner.terminate.assert_not_awaited()


# ──────────────────────────────────────────────────────── unknown session


@pytest.mark.anyio
async def test_start_unknown_session(client: AsyncClient) -> None:
    r = await client.post("/api/noriarm/games/store-play/sessions/doesnotexist/start")
    assert r.status_code == 404


@pytest.mark.anyio
async def test_serve_unknown_session(client: AsyncClient) -> None:
    r = await client.post(
        "/api/noriarm/games/store-play/sessions/doesnotexist/serve",
        json={"prompt": "give me strawberry"},
    )
    assert r.status_code == 404


@pytest.mark.anyio
async def test_events_unknown_session(client: AsyncClient) -> None:
    r = await client.get("/api/noriarm/games/store-play/sessions/doesnotexist/events")
    assert r.status_code == 404


# ──────────────────────────────────────────────────────── session unit


@pytest.mark.anyio
async def test_push_done_idempotent() -> None:
    session = StorePlaySession(session_id="test")
    session.push_done()
    assert session.status == "done"
    session.push_done()
    assert session.status == "done"
    events = []
    while not session._queue.empty():
        events.append(session._queue.get_nowait())
    assert len([e for e in events if e.get("type") == "done"]) == 1
