"""control_service.camera_pan.ros_bridge 단위 테스트 (rclpy 미사용 경로).

start() 는 rclpy import 필요 — 환경변수 누락 시 RuntimeError 만 검증.
_on_state 콜백은 SimpleNamespace 로 모킹된 JointState 로 단위 호출.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from control_service.camera_pan.ros_bridge import (
    PAN_JOINT,
    TILT_JOINT,
    CameraPanBridge,
)


def _joint_state(names: list[str], positions: list[float]) -> SimpleNamespace:
    return SimpleNamespace(name=names, position=positions)


def test_start_requires_ros_domain_id(monkeypatch) -> None:
    monkeypatch.delenv("ROS_DOMAIN_ID", raising=False)
    b = CameraPanBridge()
    with pytest.raises(RuntimeError):
        b.start()


def test_snapshot_before_any_state_is_none() -> None:
    b = CameraPanBridge()
    snap = b.snapshot()
    assert snap["pan_deg"] is None
    assert snap["tilt_deg"] is None
    assert snap["age_ms"] is None
    assert snap["ros_ok"] is False


def test_on_state_updates_snapshot() -> None:
    b = CameraPanBridge()
    msg = _joint_state([PAN_JOINT, TILT_JOINT], [85.0, 95.0])
    b._on_state(msg)
    snap = b.snapshot()
    assert snap["pan_deg"] == 85.0
    assert snap["tilt_deg"] == 95.0
    assert snap["age_ms"] is not None
    assert snap["age_ms"] >= 0


def test_on_state_order_independent() -> None:
    b = CameraPanBridge()
    # 순서 바꿔도 joint name 으로 매칭
    msg = _joint_state([TILT_JOINT, PAN_JOINT], [100.0, 70.0])
    b._on_state(msg)
    snap = b.snapshot()
    assert snap["pan_deg"] == 70.0
    assert snap["tilt_deg"] == 100.0


def test_on_state_missing_joint_ignored() -> None:
    b = CameraPanBridge()
    msg = _joint_state(["something_else"], [42.0])
    b._on_state(msg)
    snap = b.snapshot()
    assert snap["pan_deg"] is None
    assert snap["tilt_deg"] is None


def test_publish_pan_without_start_is_noop() -> None:
    """start() 전엔 _pub_pan 이 None — 호출이 raise 하지 않아야 함."""
    b = CameraPanBridge()
    b.publish_pan(90.0)  # 예외 없음
    b.publish_tilt(90.0)


def test_health_returns_required_keys(monkeypatch) -> None:
    monkeypatch.setenv("ROS_DOMAIN_ID", "211")
    b = CameraPanBridge()
    h = b.health()
    assert h["ros_domain_id"] == 211
    assert "ros_ok" in h
    assert "last_state_age_ms" in h
