"""teleop_protocol round-trip tests."""
from __future__ import annotations
import math
import pytest
from control_service.streaming.teleop_protocol import (
    TargetFrame, ArmTarget, StateFrame, ArmState,
    encode_target, decode_target, encode_state, decode_state,
    SERVO_STATUS_OK, SERVO_STATUS_SLOWED, SERVO_STATUS_STOPPED, SERVO_STATUS_ERROR,
    MAGIC, MSG_TARGET, MSG_STATE,
)


def _arm_target(x=0.30, y=0.10, z=0.45, gripper=0.55) -> ArmTarget:
    # identity quaternion
    return ArmTarget(x=x, y=y, z=z, qx=0.0, qy=0.0, qz=0.0, qw=1.0, gripper=gripper)


def test_target_both_arms_roundtrip() -> None:
    src = TargetFrame(
        ts_ms=1234567,
        left=_arm_target(0.30, 0.10, 0.45, 0.55),
        right=_arm_target(-0.30, 0.10, 0.45, 0.20),
    )
    buf = encode_target(src)
    assert buf[0] == MAGIC
    assert buf[1] == MSG_TARGET
    assert len(buf) == 37
    dst = decode_target(buf)
    assert dst.ts_ms == 1234567
    assert dst.left is not None and dst.right is not None
    assert dst.left.x == pytest.approx(0.30, abs=1e-3)
    assert dst.right.x == pytest.approx(-0.30, abs=1e-3)
    assert dst.left.gripper == pytest.approx(0.55, abs=1.0/255)
    assert dst.right.gripper == pytest.approx(0.20, abs=1.0/255)


def test_target_left_only() -> None:
    src = TargetFrame(ts_ms=42, left=_arm_target(), right=None)
    buf = encode_target(src)
    assert len(buf) == 22  # 7 header + 15 left
    dst = decode_target(buf)
    assert dst.left is not None
    assert dst.right is None


def test_target_quaternion_signed() -> None:
    # qw 음수 (회전 180° 초과) 도 round-trip
    src = TargetFrame(
        ts_ms=1,
        left=ArmTarget(x=0.0, y=0.0, z=0.0,
                       qx=0.5, qy=-0.5, qz=0.5, qw=-0.5,
                       gripper=0.5),
        right=None,
    )
    buf = encode_target(src)
    dst = decode_target(buf)
    assert dst.left.qx == pytest.approx(0.5, abs=1e-3)
    assert dst.left.qy == pytest.approx(-0.5, abs=1e-3)
    assert dst.left.qz == pytest.approx(0.5, abs=1e-3)
    assert dst.left.qw == pytest.approx(-0.5, abs=1e-3)


def test_target_position_extremes() -> None:
    # int16 mm 한계 (±32.767m). 1m 정도면 충분히 안에 있어야 함.
    src = TargetFrame(
        ts_ms=0,
        left=ArmTarget(x=1.234, y=-0.567, z=2.345,
                       qx=0, qy=0, qz=0, qw=1, gripper=0.0),
        right=None,
    )
    dst = decode_target(encode_target(src))
    assert dst.left.x == pytest.approx(1.234, abs=1e-3)
    assert dst.left.y == pytest.approx(-0.567, abs=1e-3)
    assert dst.left.z == pytest.approx(2.345, abs=1e-3)


def test_state_roundtrip() -> None:
    src = StateFrame(
        ts_ms=999,
        left=ArmState(joints=[0.1, -0.2, 0.3, 0.4, -0.5, 0.0, 1.0],
                      gripper=0.54, servo_status=SERVO_STATUS_OK),
        right=ArmState(joints=[0.0]*7, gripper=0.20, servo_status=SERVO_STATUS_SLOWED),
    )
    buf = encode_state(src)
    assert buf[0] == MAGIC
    assert buf[1] == MSG_STATE
    assert len(buf) == 37
    dst = decode_state(buf)
    assert dst.ts_ms == 999
    for a, b in zip(dst.left.joints, src.left.joints):
        assert a == pytest.approx(b, abs=1e-3)
    assert dst.right.servo_status == SERVO_STATUS_SLOWED


def test_decode_rejects_bad_magic() -> None:
    buf = bytearray(encode_target(TargetFrame(ts_ms=0, left=_arm_target(), right=None)))
    buf[0] = 0xFF
    with pytest.raises(ValueError):
        decode_target(bytes(buf))


def test_target_right_only() -> None:
    src = TargetFrame(ts_ms=42, left=None, right=_arm_target(-0.3, 0.1, 0.4, 0.2))
    buf = encode_target(src)
    assert len(buf) == 22  # 7 header + 15 right
    dst = decode_target(buf)
    assert dst.left is None
    assert dst.right is not None
    assert dst.right.x == pytest.approx(-0.3, abs=1e-3)
    assert dst.right.gripper == pytest.approx(0.2, abs=1.0/255)


def test_decode_target_truncated_arm_block() -> None:
    # 양팔 flags 인데 left 블록 하나만 들어 있는 버퍼.
    src = TargetFrame(ts_ms=0, left=ArmTarget(0,0,0,0,0,0,1,0), right=None)
    buf = bytearray(encode_target(src))
    buf[2] = 0x3  # set both has_left and has_right
    with pytest.raises(ValueError):
        decode_target(bytes(buf))


def test_decode_rejects_wrong_msg_type() -> None:
    buf = encode_state(StateFrame(
        ts_ms=0,
        left=ArmState(joints=[0]*7, gripper=0, servo_status=SERVO_STATUS_OK),
        right=ArmState(joints=[0]*7, gripper=0, servo_status=SERVO_STATUS_OK),
    ))
    with pytest.raises(ValueError):
        decode_target(buf)
