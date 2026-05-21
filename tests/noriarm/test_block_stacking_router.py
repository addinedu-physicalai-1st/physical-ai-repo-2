"""세션 모델 단위 테스트 — process / bridge 는 다루지 않는다."""
from __future__ import annotations

from control_service.noriarm.block_stacking import (
    BlockStackingSession,
    SessionStore,
)


def test_session_create_and_get() -> None:
    store = SessionStore()
    session = store.create()
    assert session.session_id
    assert session.home_event_count == 0
    assert store.get(session.session_id) is session


def test_session_increment_home_event() -> None:
    session = BlockStackingSession(session_id="s1")
    session.on_home_event(1)
    session.on_home_event(2)
    assert session.home_event_count == 2
    assert len(session.events) >= 2


def test_session_done_after_two_home_events() -> None:
    session = BlockStackingSession(session_id="s1")
    session.on_home_event(1)
    assert not session.is_done()
    session.on_home_event(2)
    assert session.is_done()
