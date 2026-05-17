"""PoseSubscriber 의 POSE_OVERRIDE_ACTIVE flag suppression 단위 테스트.

PoseSubscriber 의 _on_pose 콜백을 직접 호출 — 실 ROS 토픽 불필요.
geometry_msgs/PoseWithCovarianceStamped 만 fake 객체로 mock.
blackboard 의 flag True 면 W skip, False 면 정상 W 검증.

interfaces/__init__.py 우회 — pose_subscriber.py 만 직접 로드해 sensor_msgs / std_msgs
의존성 회피.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_REPO = Path(__file__).resolve().parents[1]
_GOGOPING_MODES_SRC = (
    _REPO / "controller" / "gogoping-controller" / "src" / "gogoping"
    / "gogoping_modes"
)
sys.path.insert(0, str(_GOGOPING_MODES_SRC))

# geometry_msgs / rclpy.qos 가 없는 환경에서도 import 가능하게 stub
try:
    from geometry_msgs.msg import PoseWithCovarianceStamped  # noqa: F401
except ImportError:
    fake_msg = ModuleType("geometry_msgs.msg")
    fake_msg.PoseWithCovarianceStamped = object  # type: ignore[attr-defined]
    fake_pkg = ModuleType("geometry_msgs")
    fake_pkg.msg = fake_msg  # type: ignore[attr-defined]
    sys.modules["geometry_msgs"] = fake_pkg
    sys.modules["geometry_msgs.msg"] = fake_msg

try:
    from rclpy.qos import QoSProfile  # noqa: F401
except ImportError:
    class _FakeEnum:
        TRANSIENT_LOCAL = "TRANSIENT_LOCAL"
        VOLATILE = "VOLATILE"
        RELIABLE = "RELIABLE"
    fake_qos = ModuleType("rclpy.qos")
    fake_qos.QoSProfile = lambda **kwargs: None  # type: ignore[attr-defined]
    fake_qos.DurabilityPolicy = _FakeEnum  # type: ignore[attr-defined]
    fake_qos.ReliabilityPolicy = _FakeEnum  # type: ignore[attr-defined]
    fake_rclpy = ModuleType("rclpy")
    sys.modules.setdefault("rclpy", fake_rclpy)
    sys.modules["rclpy.qos"] = fake_qos

import py_trees  # noqa: E402
from py_trees.common import Access  # noqa: E402

from gogoping_modes.bt.blackboard import Keys, init_blackboard  # noqa: E402

# pose_subscriber 모듈 파일만 직접 로드해 우회.
_pose_path = _GOGOPING_MODES_SRC / "gogoping_modes" / "interfaces" / "pose_subscriber.py"
_spec = importlib.util.spec_from_file_location(
    "gogoping_modes.interfaces.pose_subscriber_test_module", _pose_path
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)  # type: ignore[union-attr]
PoseSubscriber = _module.PoseSubscriber


def _fake_pose_msg(x: float, y: float, qw: float = 1.0, qz: float = 0.0):
    """geometry_msgs/PoseWithCovarianceStamped 흉내 — pose.pose.position / orientation."""
    return SimpleNamespace(
        pose=SimpleNamespace(
            pose=SimpleNamespace(
                position=SimpleNamespace(x=x, y=y, z=0.0),
                orientation=SimpleNamespace(x=0.0, y=0.0, z=qz, w=qw),
            )
        )
    )


class _FakeNode:
    """rclpy.Node 시그니처 흉내 — create_subscription 만."""
    def create_subscription(self, *args, **kwargs):
        return None


@pytest.fixture
def setup_bb():
    init_blackboard()
    flag = py_trees.blackboard.Client(name="t_flag")
    flag.register_key(key=Keys.POSE_OVERRIDE_ACTIVE, access=Access.WRITE)
    pose_reader = py_trees.blackboard.Client(name="t_pose_reader")
    pose_reader.register_key(key=Keys.ROBOT_POSE, access=Access.READ)
    return flag, pose_reader


def test_normal_write_when_override_off(setup_bb):
    """POSE_OVERRIDE_ACTIVE=False 면 amcl_pose 메시지가 blackboard 에 정상 반영."""
    flag, reader = setup_bb
    flag.set(Keys.POSE_OVERRIDE_ACTIVE, False)

    sub = PoseSubscriber(_FakeNode())
    sub._on_pose(_fake_pose_msg(3.0, 4.0))

    pose = reader.get(Keys.ROBOT_POSE)
    assert pose["x"] == 3.0
    assert pose["y"] == 4.0


def test_skip_write_when_override_on(setup_bb):
    """POSE_OVERRIDE_ACTIVE=True 면 amcl_pose 메시지가 와도 blackboard W skip."""
    flag, reader = setup_bb
    flag.set(Keys.POSE_OVERRIDE_ACTIVE, True)

    bb = py_trees.blackboard.Client(name="t_override_writer")
    bb.register_key(key=Keys.ROBOT_POSE, access=Access.WRITE)
    bb.set(Keys.ROBOT_POSE, {"x": 99.0, "y": 88.0, "yaw": 0.0})

    sub = PoseSubscriber(_FakeNode())
    sub._on_pose(_fake_pose_msg(3.0, 4.0))

    pose = reader.get(Keys.ROBOT_POSE)
    assert pose["x"] == 99.0, "override 값 유지되어야 함"
    assert pose["y"] == 88.0


def test_resume_after_override_cleared(setup_bb):
    """override 해제 후 다음 amcl_pose 메시지부터 정상 W 복귀."""
    flag, reader = setup_bb

    sub = PoseSubscriber(_FakeNode())

    flag.set(Keys.POSE_OVERRIDE_ACTIVE, True)
    bb = py_trees.blackboard.Client(name="t_override_writer2")
    bb.register_key(key=Keys.ROBOT_POSE, access=Access.WRITE)
    bb.set(Keys.ROBOT_POSE, {"x": 50.0, "y": 50.0, "yaw": 0.0})
    sub._on_pose(_fake_pose_msg(1.0, 1.0))
    assert reader.get(Keys.ROBOT_POSE)["x"] == 50.0

    flag.set(Keys.POSE_OVERRIDE_ACTIVE, False)
    sub._on_pose(_fake_pose_msg(7.0, 8.0))
    pose = reader.get(Keys.ROBOT_POSE)
    assert pose["x"] == 7.0
    assert pose["y"] == 8.0


def test_default_is_live_pose():
    """init_blackboard 의 POSE_OVERRIDE_ACTIVE 기본값은 False — amcl_pose 정상 W."""
    init_blackboard()
    reader = py_trees.blackboard.Client(name="t_default_reader")
    reader.register_key(key=Keys.POSE_OVERRIDE_ACTIVE, access=Access.READ)
    assert reader.get(Keys.POSE_OVERRIDE_ACTIVE) is False
