"""Binary teleop wire protocol for doctor ↔ control-service.

스펙: docs/superpowers/specs/2026-05-26-doctor-ui-telemedicine-design.md §4.

Frame header (모든 frame 공통, little-endian, 7 bytes):
    magic[B]    = 0xDC
    msg_type[B] = 0x01 target / 0x02 state
    flags[B]    = bit0=has_left, bit1=has_right  (target)
                  bit0..1=L servo_status, bit2..3=R servo_status (state)
    ts_ms[I]    = uint32 ms (세션 시작 기준)

Arm block: target=15 B, state=15 B. Total frame: 7 + 15*2 = 37 B (both arms).

저빈도 메시지 (session/event) 는 별도 JSON text frame — 본 모듈 범위 외.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

MAGIC = 0xDC
MSG_TARGET = 0x01
MSG_STATE = 0x02

SERVO_STATUS_OK = 0
SERVO_STATUS_SLOWED = 1
SERVO_STATUS_STOPPED = 2
SERVO_STATUS_ERROR = 3

_HEADER = struct.Struct("<BBBI")  # magic, msg_type, flags, ts_ms
_TARGET_ARM = struct.Struct("<hhhhhhhB")  # x,y,z mm + qx,qy,qz,qw + gripper
_STATE_ARM = struct.Struct("<hhhhhhhB")   # 7 joints (×10000 rad) + gripper

_POS_SCALE = 1000.0       # m → mm
_QUAT_SCALE = 32767.0
_JOINT_SCALE = 10000.0    # rad → ×10000


@dataclass
class ArmTarget:
    x: float
    y: float
    z: float
    qx: float
    qy: float
    qz: float
    qw: float
    gripper: float  # 0.0~1.0


@dataclass
class TargetFrame:
    ts_ms: int
    left: Optional[ArmTarget]
    right: Optional[ArmTarget]


@dataclass
class ArmState:
    joints: list[float]   # 7 elements (rad)
    gripper: float        # 0.0~1.0 (actual)
    servo_status: int     # 0..3


@dataclass
class StateFrame:
    ts_ms: int
    left: ArmState
    right: ArmState


def _enc_arm_target(a: ArmTarget) -> bytes:
    return _TARGET_ARM.pack(
        int(round(a.x * _POS_SCALE)),
        int(round(a.y * _POS_SCALE)),
        int(round(a.z * _POS_SCALE)),
        int(round(a.qx * _QUAT_SCALE)),
        int(round(a.qy * _QUAT_SCALE)),
        int(round(a.qz * _QUAT_SCALE)),
        int(round(a.qw * _QUAT_SCALE)),
        max(0, min(255, int(round(a.gripper * 255)))),
    )


def _dec_arm_target(buf: bytes, off: int) -> ArmTarget:
    x_mm, y_mm, z_mm, qx_i, qy_i, qz_i, qw_i, g_u = _TARGET_ARM.unpack_from(buf, off)
    return ArmTarget(
        x=x_mm / _POS_SCALE,
        y=y_mm / _POS_SCALE,
        z=z_mm / _POS_SCALE,
        qx=qx_i / _QUAT_SCALE,
        qy=qy_i / _QUAT_SCALE,
        qz=qz_i / _QUAT_SCALE,
        qw=qw_i / _QUAT_SCALE,
        gripper=g_u / 255.0,
    )


def encode_target(frame: TargetFrame) -> bytes:
    flags = (0x1 if frame.left else 0) | (0x2 if frame.right else 0)
    out = bytearray(_HEADER.pack(MAGIC, MSG_TARGET, flags, frame.ts_ms & 0xFFFFFFFF))
    if frame.left:
        out += _enc_arm_target(frame.left)
    if frame.right:
        out += _enc_arm_target(frame.right)
    return bytes(out)


def decode_target(buf: bytes) -> TargetFrame:
    if len(buf) < _HEADER.size:
        raise ValueError("target frame too short")
    magic, msg_type, flags, ts_ms = _HEADER.unpack_from(buf, 0)
    if magic != MAGIC:
        raise ValueError(f"bad magic 0x{magic:02x}")
    if msg_type != MSG_TARGET:
        raise ValueError(f"expected target msg_type, got 0x{msg_type:02x}")
    expected = _HEADER.size + (1 if (flags & 0x1) else 0) * _TARGET_ARM.size + (1 if (flags & 0x2) else 0) * _TARGET_ARM.size
    if len(buf) < expected:
        raise ValueError(f"target frame too short: {len(buf)} < {expected}")
    off = _HEADER.size
    left = None
    right = None
    if flags & 0x1:
        left = _dec_arm_target(buf, off)
        off += _TARGET_ARM.size
    if flags & 0x2:
        right = _dec_arm_target(buf, off)
    return TargetFrame(ts_ms=ts_ms, left=left, right=right)


def _enc_arm_state(s: ArmState) -> bytes:
    if len(s.joints) != 7:
        raise ValueError(f"expected 7 joints, got {len(s.joints)}")
    return _STATE_ARM.pack(
        *[max(-32768, min(32767, int(round(j * _JOINT_SCALE)))) for j in s.joints],
        max(0, min(255, int(round(s.gripper * 255)))),
    )


def _dec_arm_state(buf: bytes, off: int, servo_status: int) -> ArmState:
    fields = _STATE_ARM.unpack_from(buf, off)
    joints = [v / _JOINT_SCALE for v in fields[:7]]
    gripper = fields[7] / 255.0
    return ArmState(joints=joints, gripper=gripper, servo_status=servo_status)


def encode_state(frame: StateFrame) -> bytes:
    flags = (frame.left.servo_status & 0x3) | ((frame.right.servo_status & 0x3) << 2)
    out = bytearray(_HEADER.pack(MAGIC, MSG_STATE, flags, frame.ts_ms & 0xFFFFFFFF))
    out += _enc_arm_state(frame.left)
    out += _enc_arm_state(frame.right)
    return bytes(out)


def decode_state(buf: bytes) -> StateFrame:
    if len(buf) < _HEADER.size + 2 * _STATE_ARM.size:
        raise ValueError("state frame too short")
    magic, msg_type, flags, ts_ms = _HEADER.unpack_from(buf, 0)
    if magic != MAGIC:
        raise ValueError(f"bad magic 0x{magic:02x}")
    if msg_type != MSG_STATE:
        raise ValueError(f"expected state msg_type, got 0x{msg_type:02x}")
    left_status = flags & 0x3
    right_status = (flags >> 2) & 0x3
    off = _HEADER.size
    left = _dec_arm_state(buf, off, left_status)
    off += _STATE_ARM.size
    right = _dec_arm_state(buf, off, right_status)
    return StateFrame(ts_ms=ts_ms, left=left, right=right)
