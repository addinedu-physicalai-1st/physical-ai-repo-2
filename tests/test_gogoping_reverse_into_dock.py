"""ReverseIntoDock 단위 테스트.

ROS 의존성 없음 — cmd_vel publisher 는 Recorder 로 inject.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

from py_trees.common import Status  # noqa: E402

from gogoping_modes.bt.blackboard import init_blackboard  # noqa: E402
from gogoping_modes.bt.behaviors.navigation.reverse_into_dock import ReverseIntoDock  # noqa: E402


class _Twist:
    class _V:
        x = 0.0
        y = 0.0
        z = 0.0

    def __init__(self) -> None:
        self.linear = _Twist._V()
        self.angular = _Twist._V()


class _Recorder:
    def __init__(self) -> None:
        self.published: list[tuple[float, float]] = []  # (linear_x, angular_z)

    def publish(self, msg) -> None:
        self.published.append((float(msg.linear.x), float(msg.angular.z)))


class _Ctx:
    def __init__(self) -> None:
        self.node = None


@pytest.fixture(autouse=True)
def _init_bb():
    init_blackboard()


def _new(duration: float = 0.1, linear_x: float = -0.1):
    ctx = _Ctx()
    rev = ReverseIntoDock("reverse", ctx)
    rev._duration_sec = duration
    rev._linear_x = linear_x

    rec = _Recorder()
    rev._cmd_vel_pub = rec

    sys.modules.setdefault("geometry_msgs", type(sys)("geometry_msgs"))
    fake_msg = type(sys)("geometry_msgs.msg")
    fake_msg.Twist = _Twist
    sys.modules["geometry_msgs.msg"] = fake_msg

    rev.initialise()
    return rev, rec


def test_publishes_negative_linear_x_while_running():
    """elapsed < duration 동안 linear_x publish."""
    rev, rec = _new(duration=0.1, linear_x=-0.1)
    assert rev.update() == Status.RUNNING
    assert rec.published[-1] == (-0.1, 0.0)


def test_returns_success_after_duration():
    """duration 경과 후 SUCCESS + 정지 publish."""
    rev, rec = _new(duration=0.05)
    time.sleep(0.06)
    assert rev.update() == Status.SUCCESS
    assert rec.published[-1] == (0.0, 0.0)


def test_stays_running_before_duration():
    """duration 안에서는 RUNNING 지속."""
    rev, _rec = _new(duration=1.0)
    assert rev.update() == Status.RUNNING
    assert rev.update() == Status.RUNNING
    assert rev.update() == Status.RUNNING


def test_terminate_publishes_stop():
    """트리 중간 종료 시 cmd_vel = 0."""
    rev, rec = _new(duration=1.0)
    rev.update()  # 후진 시작
    rec.published.clear()
    rev.terminate(Status.INVALID)
    assert (0.0, 0.0) in rec.published


def test_terminate_idempotent():
    """terminate 여러 번 호출 안전."""
    rev, _rec = _new()
    rev.terminate(Status.INVALID)
    rev.terminate(Status.SUCCESS)


def test_initialise_resets_timer():
    """initialise() 재호출 시 timer 리셋."""
    rev, _rec = _new(duration=0.05)
    time.sleep(0.06)
    assert rev.update() == Status.SUCCESS  # 1차

    rev.initialise()  # 리셋
    assert rev.update() == Status.RUNNING  # 막 시작
    time.sleep(0.06)
    assert rev.update() == Status.SUCCESS  # 다시 SUCCESS


def test_custom_linear_x():
    """파라미터로 후진 속도 변경 가능."""
    rev, rec = _new(duration=1.0, linear_x=-0.25)
    rev.update()
    assert rec.published[-1] == (-0.25, 0.0)


def test_no_pub_when_publisher_missing():
    """publisher None 이어도 예외 없이 동작."""
    ctx = _Ctx()
    rev = ReverseIntoDock("rev", ctx)
    rev._duration_sec = 0.05
    rev._cmd_vel_pub = None
    rev.initialise()
    rev.update()  # 예외 없음
    time.sleep(0.06)
    assert rev.update() == Status.SUCCESS
