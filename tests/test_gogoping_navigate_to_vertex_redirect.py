"""NavigateToVertex 이동 중 목적지 변경(redirect) 단위 테스트.

배경: GOTO 중 새 GOTO(다른 dest) 요청 시 goal_reconciler 가 destination_key
블랙보드만 갱신하고 FSM trigger 는 안 쏜다(same_state). 그래서 실행 중이던
NavigateToVertex 가 새 dest 를 안 읽어 옛 목적지로 계속 가던 버그.

수정: NavigateToVertex.update() 가 매 tick 블랙보드 target 을 재확인 →
바뀌었으면 진행 중 goal cancel 후 새 target 으로 재전송.

ROS 의존성 없음 — conftest 가 rclpy/gogoping_msgs stub. ActionClient 는 fake inject.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"),
)

import py_trees  # noqa: E402
from py_trees.common import Status  # noqa: E402

from gogoping_modes.bt.blackboard import Keys, init_blackboard  # noqa: E402
from gogoping_modes.bt.behaviors.navigation.navigate_to_vertex import (  # noqa: E402
    NavigateToVertex,
)


class _FakeFuture:
    """rclpy future mimic. auto_fire=True 면 add_done_callback 즉시 콜백 호출(동기)."""

    def __init__(self, result, auto_fire: bool) -> None:
        self._result = result
        self._auto = auto_fire

    def add_done_callback(self, cb) -> None:
        if self._auto:
            cb(self)

    def result(self):
        return self._result


class _FakeGoalHandle:
    def __init__(self) -> None:
        self.accepted = True
        self.cancel_called = 0

    def get_result_async(self):
        # 결과 future 는 안 fire → behavior 는 RUNNING 유지
        return _FakeFuture(None, auto_fire=False)

    def cancel_goal_async(self):
        self.cancel_called += 1
        return _FakeFuture(None, auto_fire=False)


class _FakeClient:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.handles: list[_FakeGoalHandle] = []

    def server_is_ready(self) -> bool:
        return True

    def wait_for_server(self, timeout_sec: float = 0.0) -> bool:
        return True

    def send_goal_async(self, goal):
        self.sent.append(goal.target_name)
        gh = _FakeGoalHandle()
        self.handles.append(gh)
        return _FakeFuture(gh, auto_fire=True)  # gh 동기 전달


def _set_dest(value: str) -> None:
    bb = py_trees.blackboard.Client(name="_set_dest")
    bb.register_key(key=Keys.DESTINATION_KEY, access=py_trees.common.Access.WRITE)
    bb.set(Keys.DESTINATION_KEY, value)


def _new(dest: str):
    init_blackboard()
    _set_dest(dest)
    beh = NavigateToVertex(target_key=Keys.DESTINATION_KEY)
    client = _FakeClient()
    beh._client = client
    beh.initialise()
    return beh, client


def test_initial_goal_sent():
    beh, client = _new("A")
    assert client.sent == ["A"]
    assert beh.update() == Status.RUNNING


def test_dest_change_midflight_cancels_old_and_resends():
    """이동 중(RUNNING) dest A→B 변경 → 옛 goal cancel + 새 goal('B') 전송."""
    beh, client = _new("A")
    assert beh.update() == Status.RUNNING
    old_gh = client.handles[0]

    _set_dest("B")  # 이동 중 목적지 변경
    assert beh.update() == Status.RUNNING

    assert client.sent == ["A", "B"], "새 목적지로 재전송돼야 함"
    assert old_gh.cancel_called == 1, "옛 goal 은 취소돼야 함"
    assert beh._last_target == "B"


def test_same_dest_no_resend():
    """같은 dest 재요청은 재전송/취소 없음 (idempotent)."""
    beh, client = _new("A")
    beh.update()
    _set_dest("A")  # 동일
    beh.update()
    assert client.sent == ["A"], "동일 dest 는 재전송 안 함"
    assert client.handles[0].cancel_called == 0


def test_dest_change_after_done_ignored():
    """이미 성공/실패로 끝난 뒤 dest 바뀌어도 재전송 안 함."""
    beh, client = _new("A")
    beh.update()
    beh._result_status = "succeeded"  # 도착 처리됨
    _set_dest("B")
    assert beh.update() == Status.SUCCESS
    assert client.sent == ["A"], "종료 후엔 재전송 없음"
