"""WebRTCRelay 단위 테스트.

라이브 영상 relay 는 최신 프레임만 중요 — MediaRelay.subscribe 를 buffered=False 로
호출해야 한다. buffered=True(기본값)면 consumer 마다 무한 asyncio.Queue 가 생겨
느린 consumer 에서 프레임이 끝없이 쌓이고(지연 폭증) → 따라잡을 때 밀린 프레임이
폭발 재생되거나 사실상 freeze(검정) 된다. 이 회귀를 막는 테스트.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from control_service.streaming.webrtc_relay import WebRTCRelay


def _video_transceiver():
    tr = MagicMock()
    tr.kind = "video"
    tr.sender = MagicMock()
    return tr


def test_attach_track_to_consumer_subscribes_unbuffered():
    relay = WebRTCRelay()
    relay._producer_track = MagicMock(name="producer_track")
    proxy = MagicMock(name="proxy_track")
    relay._relay = MagicMock()
    relay._relay.subscribe.return_value = proxy

    tr = _video_transceiver()
    pc = MagicMock()
    pc.getTransceivers.return_value = [tr]

    relay.attach_track_to_consumer(pc)

    # 핵심: buffered=False 로 subscribe (라이브 — 오래된 프레임 버리고 최신만)
    relay._relay.subscribe.assert_called_once_with(relay._producer_track, buffered=False)
    tr.sender.replaceTrack.assert_called_once_with(proxy)
    assert tr.direction == "sendonly"


def test_attach_track_to_consumer_noop_without_producer():
    """producer track 없으면 subscribe 안 함 (안전)."""
    relay = WebRTCRelay()
    relay._producer_track = None
    relay._relay = MagicMock()

    relay.attach_track_to_consumer(MagicMock())

    relay._relay.subscribe.assert_not_called()
