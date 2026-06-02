"""AlignToDock 단위 테스트.

ROS 의존성 없음 — py_trees 만 사용. cmd_vel publisher 는 Recorder 로 inject.
"""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import pytest

# gogoping_modes 패키지 path 등록
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "controller" / "gogoping-controller" / "src" / "gogoping" / "gogoping_modes"))

import py_trees  # noqa: E402
from py_trees.common import Status  # noqa: E402

from gogoping_modes.bt.blackboard import Keys, init_blackboard  # noqa: E402
from gogoping_modes.bt.behaviors.navigation.align_to_dock import AlignToDock  # noqa: E402


class _Twist:
    """geometry_msgs.msg.Twist mimic — linear / angular 분리."""

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
        self.node = None  # ROS param 미사용 — default


@pytest.fixture(autouse=True)
def _init_bb():
    init_blackboard()


def _set_pose(yaw: float) -> None:
    bb = py_trees.blackboard.Client(name=f"_set_pose_{yaw}")
    bb.register_key(key=Keys.ROBOT_POSE, access=py_trees.common.Access.WRITE)
    bb.set(Keys.ROBOT_POSE, {"x": 0.0, "y": 0.0, "yaw": yaw})


def _set_target_yaw(yaw: float) -> None:
    bb = py_trees.blackboard.Client(name=f"_set_target_{yaw}")
    bb.register_key(key=Keys.CHARGING_DOCK_TARGET_YAW, access=py_trees.common.Access.WRITE)
    bb.set(Keys.CHARGING_DOCK_TARGET_YAW, yaw)


def _new(tolerance: float = 0.05, speed: float = 0.5, timeout: float = 10.0):
    ctx = _Ctx()
    align = AlignToDock("align", ctx)
    align._tolerance = tolerance
    align._angular_speed = speed
    align._timeout_sec = timeout

    rec = _Recorder()
    align._cmd_vel_pub = rec

    # Twist 클래스를 module 안에 inject — _publish_twist 가 import 하는 자리.
    # _publish_twist 가 from geometry_msgs.msg import Twist 를 부르므로 sys.modules 에 fake 모듈 등록.
    sys.modules.setdefault("geometry_msgs", type(sys)("geometry_msgs"))
    fake_msg = type(sys)("geometry_msgs.msg")
    fake_msg.Twist = _Twist
    sys.modules["geometry_msgs.msg"] = fake_msg

    align.initialise()
    return align, rec


def test_already_aligned_returns_success_immediately():
    _set_pose(yaw=-math.pi / 2)
    _set_target_yaw(yaw=-math.pi / 2)
    align, rec = _new()
    assert align.update() == Status.SUCCESS
    # 정지 publish 한 번
    assert rec.published == [(0.0, 0.0)]


def test_positive_error_rotates_positive_direction():
    """current=0, target=+π/4 → angular.z > 0."""
    _set_pose(yaw=0.0)
    _set_target_yaw(yaw=math.pi / 4)
    align, rec = _new()
    assert align.update() == Status.RUNNING
    assert rec.published[-1] == (0.0, 0.5)


def test_negative_error_rotates_negative_direction():
    """current=0, target=-π/2 → angular.z < 0."""
    _set_pose(yaw=0.0)
    _set_target_yaw(yaw=-math.pi / 2)
    align, rec = _new()
    assert align.update() == Status.RUNNING
    assert rec.published[-1] == (0.0, -0.5)


def test_wraps_around_pi_boundary():
    """current=+3, target=-3 → 짧은 경로 (음수) 가 양수보다 멀지 않은지."""
    # target - current = -6, wrap = -6 + 2π ≈ +0.283 → 양수 회전
    _set_pose(yaw=3.0)
    _set_target_yaw(yaw=-3.0)
    align, rec = _new()
    assert align.update() == Status.RUNNING
    # 양수 방향 (짧은 경로) 으로 회전
    assert rec.published[-1][1] > 0


def test_decelerates_near_target_not_full_speed():
    """비례 감속: 목표 근처(밴드 밖이지만 가까움)에선 풀스피드보다 느려야 한다.

    bang-bang 이면 error 0.2 에서도 0.5 를 내보내 오버슈트→왔다갔다. 비례 제어면
    kp(1.5)*0.2 = 0.3 < max(0.5) 로 감속되어야 한다.
    """
    _set_pose(yaw=0.0)
    _set_target_yaw(yaw=0.2)  # error 0.2 rad, tolerance 0.05 → 밴드 밖
    align, rec = _new(tolerance=0.05)
    assert align.update() == Status.RUNNING
    angular = rec.published[-1][1]
    assert angular == pytest.approx(0.3, abs=1e-6)
    assert abs(angular) < 0.5


def test_decelerates_monotonically_as_error_shrinks():
    """목표에 가까울수록 |속도| 가 작아져야 오버슈트가 안 난다."""
    def _speed_at(err: float) -> float:
        _set_pose(yaw=0.0)
        _set_target_yaw(yaw=err)
        align, rec = _new(tolerance=0.05)
        align.update()
        return abs(rec.published[-1][1])

    assert _speed_at(0.5) >= _speed_at(0.25) >= _speed_at(0.12)
    assert _speed_at(0.12) < 0.5


def test_within_tolerance_returns_success():
    """error 가 tolerance 안이면 즉시 SUCCESS."""
    _set_pose(yaw=0.04)
    _set_target_yaw(yaw=0.0)
    align, rec = _new(tolerance=0.05)
    assert align.update() == Status.SUCCESS
    assert rec.published == [(0.0, 0.0)]


def test_timeout_returns_failure():
    """timeout 초과 시 FAILURE + 정지."""
    _set_pose(yaw=0.0)
    _set_target_yaw(yaw=math.pi)  # 절대 못 도달 (회전 안 시킴 — 시간만 흘림)
    align, rec = _new(timeout=0.05)
    align.update()  # RUNNING
    time.sleep(0.06)
    assert align.update() == Status.FAILURE
    # 마지막 publish 가 정지
    assert rec.published[-1] == (0.0, 0.0)


def test_terminate_publishes_stop():
    """트리 중간 종료 시 cmd_vel = 0 publish."""
    _set_pose(yaw=0.0)
    _set_target_yaw(yaw=math.pi / 2)
    align, rec = _new()
    align.update()  # RUNNING — 회전 시작
    rec.published.clear()
    align.terminate(Status.INVALID)
    assert (0.0, 0.0) in rec.published


def test_terminate_idempotent():
    """terminate 여러 번 호출 안전."""
    _set_pose(yaw=0.0)
    _set_target_yaw(yaw=0.0)
    align, _rec = _new()
    align.terminate(Status.INVALID)
    align.terminate(Status.SUCCESS)


def test_missing_pose_returns_failure():
    """ROBOT_POSE 가 비정상이면 FAILURE."""
    # blackboard 의 ROBOT_POSE 를 깨진 형태로 세팅
    bb = py_trees.blackboard.Client(name="_break_pose")
    bb.register_key(key=Keys.ROBOT_POSE, access=py_trees.common.Access.WRITE)
    bb.set(Keys.ROBOT_POSE, None)
    _set_target_yaw(yaw=0.0)

    align, rec = _new()
    assert align.update() == Status.FAILURE
    assert rec.published[-1] == (0.0, 0.0)
