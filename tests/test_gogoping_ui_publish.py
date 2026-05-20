"""UIPublish (범용 common behavior) 단위 테스트.

message dict 1회 publish 후 즉시 SUCCESS — hideseek / lullaby_stop 등이 재사용.
MagicMock 으로 ctx.ui 검증.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from py_trees.common import Status  # noqa: E402

from gogoping_modes.bt.behaviors.common.ui_publish import UIPublish  # noqa: E402


def _ctx_with_mock_ui():
    ctx = MagicMock()
    ctx.ui = MagicMock()
    return ctx


def test_update_returns_success_immediately():
    """update 한 번 만에 SUCCESS."""
    ctx = _ctx_with_mock_ui()
    node = UIPublish("test_publish", ctx, message={"event": "x"})
    assert node.update() == Status.SUCCESS


def test_update_calls_publish_event_once_with_message():
    """publish_event 정확히 1회 호출, 인자 = message dict."""
    ctx = _ctx_with_mock_ui()
    msg = {"event": "announce", "text": "찾았다!"}
    node = UIPublish("AnnounceFound", ctx, message=msg)
    node.update()
    ctx.ui.publish_event.assert_called_once_with(msg)


def test_initialise_does_not_publish():
    """initialise 는 no-op — publish 는 update 에서만."""
    ctx = _ctx_with_mock_ui()
    node = UIPublish("test", ctx, message={"event": "x"})
    node.initialise()
    ctx.ui.publish_event.assert_not_called()


def test_arbitrary_message_passed_through():
    """다른 message 인스턴스도 그대로 전달."""
    ctx = _ctx_with_mock_ui()
    msg = {"event": "countdown_start", "seconds": 30}
    node = UIPublish("CountdownStart", ctx, message=msg)
    node.update()
    ctx.ui.publish_event.assert_called_once_with(msg)


def test_re_activation_publishes_again():
    """재활성화 (initialise → update) 시 publish 다시 호출 — Selector(memory=False)
    re-entry / hideseek 의 announce 반복 등.

    py_trees 의 표준 lifecycle 에 따라 직전 status 가 SUCCESS 면 다음 tick 에 자동
    initialise 호출. 본 behavior 는 초기화 후 update 가 publish 다시 발행.
    """
    ctx = _ctx_with_mock_ui()
    msg = {"event": "announce", "text": "찾았다!"}
    node = UIPublish("AnnounceFound", ctx, message=msg)

    # cycle 1
    node.initialise()
    assert node.update() == Status.SUCCESS

    # cycle 2 (재활성화)
    node.initialise()
    assert node.update() == Status.SUCCESS

    # 두 번 publish 됐는지
    assert ctx.ui.publish_event.call_count == 2
    ctx.ui.publish_event.assert_called_with(msg)  # 마지막 호출의 인자 확인
