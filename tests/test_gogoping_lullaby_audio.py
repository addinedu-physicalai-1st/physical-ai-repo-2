"""LullabyAudio behavior 단위 테스트.

initialise → play publish, update → RUNNING, terminate → stop publish (idempotent).
재진입 시 _stop_published flag 가 initialise 에서 리셋되어 두 사이클 동안 stop 도 2회.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from py_trees.common import Status  # noqa: E402

from gogoping_modes.bt.behaviors.lullaby.lullaby_audio import LullabyAudio  # noqa: E402


def _ctx_with_mock_ui():
    ctx = MagicMock()
    ctx.ui = MagicMock()
    return ctx


def test_initialise_publishes_play_message():
    """initialise → publish_event(PLAY_MSG) 1회."""
    ctx = _ctx_with_mock_ui()
    audio = LullabyAudio("BT_lullaby_sub", ctx)
    audio.initialise()
    ctx.ui.publish_event.assert_called_once_with(LullabyAudio.PLAY_MSG)


def test_update_always_returns_running():
    """update 매 호출 RUNNING — publish 호출 안 함."""
    ctx = _ctx_with_mock_ui()
    audio = LullabyAudio("BT_lullaby_sub", ctx)
    audio.initialise()
    ctx.ui.publish_event.reset_mock()
    for _ in range(10):
        assert audio.update() == Status.RUNNING
    ctx.ui.publish_event.assert_not_called()


def test_terminate_publishes_stop_message():
    """terminate → publish_event(STOP_MSG) 1회."""
    ctx = _ctx_with_mock_ui()
    audio = LullabyAudio("BT_lullaby_sub", ctx)
    audio.initialise()
    ctx.ui.publish_event.reset_mock()
    audio.terminate(Status.INVALID)
    ctx.ui.publish_event.assert_called_once_with(LullabyAudio.STOP_MSG)


def test_terminate_is_idempotent():
    """terminate 여러 번 호출돼도 stop publish 는 1회만."""
    ctx = _ctx_with_mock_ui()
    audio = LullabyAudio("BT_lullaby_sub", ctx)
    audio.initialise()
    ctx.ui.publish_event.reset_mock()
    audio.terminate(Status.INVALID)
    audio.terminate(Status.INVALID)
    audio.terminate(Status.INVALID)
    ctx.ui.publish_event.assert_called_once_with(LullabyAudio.STOP_MSG)


def test_re_entry_resets_stop_flag():
    """initialise 가 _stop_published 리셋 → 두 사이클 = play 2회 + stop 2회."""
    ctx = _ctx_with_mock_ui()
    audio = LullabyAudio("BT_lullaby_sub", ctx)
    # cycle 1
    audio.initialise()
    audio.terminate(Status.INVALID)
    # cycle 2
    audio.initialise()
    audio.terminate(Status.INVALID)
    assert ctx.ui.publish_event.call_count == 4


def test_play_and_stop_message_constants():
    """클래스 상수 형태 검증 — frontend contract."""
    assert LullabyAudio.AUDIO_SRC == "lullaby.mp3"
    assert LullabyAudio.PLAY_MSG == {
        "event": "lullaby_play",
        "src": LullabyAudio.AUDIO_SRC,
        "loop": True,
    }
    assert LullabyAudio.STOP_MSG == {"event": "lullaby_stop"}


def test_cold_terminate_does_not_publish():
    """initialise 없이 terminate 호출 → STOP_MSG publish 안 됨.

    재생 안 시작했는데 정지 신호 보내는 안티-패턴 회피. __init__ 가 _stop_published=True
    로 초기화하여 cold terminate 를 no-op 으로 만든다.
    """
    ctx = _ctx_with_mock_ui()
    audio = LullabyAudio("BT_lullaby_sub", ctx)
    audio.terminate(audio.status)  # initialise 없이 바로 terminate
    ctx.ui.publish_event.assert_not_called()
