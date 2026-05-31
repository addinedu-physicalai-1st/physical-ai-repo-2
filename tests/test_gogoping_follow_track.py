"""FollowTrack 단위 테스트 — py_trees only, ROS 불필요."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(
    _REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"
))

import py_trees  # noqa: E402
from py_trees.common import Access, Status  # noqa: E402

from gogoping_modes.bt.blackboard import Keys, init_blackboard  # noqa: E402
from gogoping_modes.bt.behaviors.perception.follow_track import (  # noqa: E402
    FollowTrack,
    tracking_state_to_blackboard,
)


class _MsgStub:
    """TrackingState 유사 duck-type."""
    def __init__(self, *, matched, teacher_id="", mode="idle", bbox=(0, 0, 0, 0)):
        self.matched = matched
        self.teacher_id = teacher_id
        self.mode = mode
        self.bbox_x1, self.bbox_y1, self.bbox_x2, self.bbox_y2 = bbox


def test_pure_matched_writes_all():
    msg = _MsgStub(matched=True, teacher_id="t123", mode="tracking", bbox=(10, 20, 30, 40))
    out = tracking_state_to_blackboard(msg, now=111.0)
    assert out[Keys.TARGET_VISIBLE] is True
    assert out[Keys.TARGET_PERSON_ID] == "t123"
    assert out[Keys.TARGET_SEEN_AT] == 111.0
    assert out[Keys.TARGET_FACE_BBOX] == (10, 20, 30, 40)


def test_pure_unmatched_skips_seen_and_bbox():
    msg = _MsgStub(matched=False, teacher_id="t123", mode="lost")
    out = tracking_state_to_blackboard(msg, now=222.0)
    assert out[Keys.TARGET_VISIBLE] is False
    assert out[Keys.TARGET_PERSON_ID] == "t123"
    assert Keys.TARGET_SEEN_AT not in out
    assert Keys.TARGET_FACE_BBOX not in out


class _Ctx:
    """node 없음 — setup 이 구독 skip (ROS 불필요)."""
    node = None


@pytest.fixture
def reader():
    init_blackboard()
    c = py_trees.blackboard.Client(name="reader")
    for k in (Keys.TARGET_VISIBLE, Keys.TARGET_PERSON_ID,
              Keys.TARGET_SEEN_AT, Keys.TARGET_FACE_BBOX):
        c.register_key(key=k, access=Access.READ)
    return c


def test_update_writes_and_runs(reader):
    ft = FollowTrack("FollowTrack", _Ctx(), now_fn=lambda: 999.0)
    ft.setup()
    ft.initialise()
    ft._on_tracking_state(_MsgStub(matched=True, teacher_id="t9",
                                   mode="tracking", bbox=(1, 2, 3, 4)))
    status = ft.update()
    assert status == Status.RUNNING
    assert reader.get(Keys.TARGET_VISIBLE) is True
    assert reader.get(Keys.TARGET_PERSON_ID) == "t9"
    assert reader.get(Keys.TARGET_SEEN_AT) == 999.0
    assert reader.get(Keys.TARGET_FACE_BBOX) == (1, 2, 3, 4)
    assert ft.feedback_message == "tracking"


def test_update_never_success_when_lost(reader):
    """⚠️ FOLLOW self-complete 금지 — 어떤 상태든 RUNNING."""
    ft = FollowTrack("FollowTrack", _Ctx())
    ft.setup()
    ft.initialise()
    ft._on_tracking_state(_MsgStub(matched=False, mode="lost"))
    assert ft.update() == Status.RUNNING


def test_update_no_msg_is_running(reader):
    """메시지 미수신에도 RUNNING (크래시 X)."""
    ft = FollowTrack("FollowTrack", _Ctx())
    ft.setup()
    ft.initialise()
    assert ft.update() == Status.RUNNING


class _FullCtx:
    """BT_follow_main.build 용 — 모든 monitor __init__ 이 node 를 getattr 로 guard."""
    node = None
    map_cache = None

    def __init__(self):
        class _FSM:
            current_state = "FOLLOW"
            def trigger(self, *a, **k):
                pass
        self.fsm = _FSM()


def test_follow_tree_body_is_followtrack():
    init_blackboard()
    from gogoping_modes.bt.trees.main_trees import BT_follow_main
    tree = BT_follow_main.build(_FullCtx())
    body = tree.children[-1]  # build_active_main_tree 가 body 를 마지막에 append
    assert isinstance(body, FollowTrack)
    assert body.name == "FollowTrack"
