"""bridge 의 home pose 이벤트 listener 가 JointState 콜백에서 트리거되는지."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytest.importorskip("rclpy")

from control_service.noriarm.ros_bridge import _home_pose_listener_factory


def test_factory_returns_callable_that_increments_on_home() -> None:
    received: list[int] = []
    cb = _home_pose_listener_factory(
        joint_names=["joint1", "joint2", "joint3", "joint4", "joint5"],
        on_event=lambda count: received.append(count),
    )
    # 첫 frame — 멀리.
    cb({"name": ["joint1", "joint2", "joint3", "joint4", "joint5"], "position": [0.5, 0, 0, 0, 0], "stamp": {"sec": 0, "nanosec": 0}})
    assert received == []
    # 두번째 frame — home 진입.
    cb({"name": ["joint1", "joint2", "joint3", "joint4", "joint5"], "position": [0, 0, 0, 0, 0], "stamp": {"sec": 1, "nanosec": 0}})
    # 0.5s 미만 — 미발화.
    assert received == []
    # 세번째 frame — 1.5s, holding window 통과.
    cb({"name": ["joint1", "joint2", "joint3", "joint4", "joint5"], "position": [0, 0, 0, 0, 0], "stamp": {"sec": 1, "nanosec": 600_000_000}})
    assert received == [1]


def test_factory_ignores_missing_joints() -> None:
    received: list[int] = []
    cb = _home_pose_listener_factory(
        joint_names=["joint1", "joint2", "joint3", "joint4", "joint5"],
        on_event=lambda count: received.append(count),
    )
    cb({"name": ["other"], "position": [0.0], "stamp": {"sec": 0, "nanosec": 0}})
    assert received == []
