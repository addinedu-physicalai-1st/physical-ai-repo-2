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


# ── Joint passthrough frame (0x03) — leader/follower 관절 스트림 (cross-machine) ──
# 원격 진찰 leader↔follower joint 스트림용. JSON {"name":[...], "position":[...]}
# 를 대체하는 바이너리: 관절 이름은 CANONICAL_JOINTS 고정 순서로 암시하고, 어떤
# 관절이 실렸는지는 16-bit mask 로 표기 → 이름 문자열 반복 전송을 제거한다.
#
#   magic[B]=0xDC | msg_type[B]=0x03 | mask[H]=present(16 관절)
#   + int16 × popcount(mask)  (position × 10000; rad / prismatic m 공용)
#
# 16 관절 모두 실어도 4 + 32 = 36 B (JSON ~400 B 대비 1/10 이하).
MSG_JOINTS = 0x03

CANONICAL_JOINTS = (
    "openarm_left_joint1", "openarm_left_joint2", "openarm_left_joint3",
    "openarm_left_joint4", "openarm_left_joint5", "openarm_left_joint6",
    "openarm_left_joint7", "openarm_left_finger_joint1",
    "openarm_right_joint1", "openarm_right_joint2", "openarm_right_joint3",
    "openarm_right_joint4", "openarm_right_joint5", "openarm_right_joint6",
    "openarm_right_joint7", "openarm_right_finger_joint1",
)
_JOINT_INDEX = {name: i for i, name in enumerate(CANONICAL_JOINTS)}
_JOINTS_HEADER = struct.Struct("<BBH")  # magic, msg_type, mask(uint16)


def encode_joints(names, positions) -> bytes:
    """``{name, position}`` → 바이너리 joint frame.

    CANONICAL_JOINTS 에 없는 이름은 버린다 (alias 없는 보조 joint 등).
    """
    slots: dict[int, float] = {}
    for n, p in zip(names, positions):
        idx = _JOINT_INDEX.get(n)
        if idx is not None:
            slots[idx] = float(p)
    mask = 0
    vals = []
    for i in range(len(CANONICAL_JOINTS)):
        if i in slots:
            mask |= (1 << i)
            v = int(round(slots[i] * _JOINT_SCALE))
            vals.append(max(-32768, min(32767, v)))
    out = bytearray(_JOINTS_HEADER.pack(MAGIC, MSG_JOINTS, mask))
    if vals:
        out += struct.pack(f"<{len(vals)}h", *vals)
    return bytes(out)


def decode_joints(buf: bytes):
    """바이너리 joint frame → ``(names, positions)`` — CANONICAL_JOINTS 순서로 복원."""
    if len(buf) < _JOINTS_HEADER.size:
        raise ValueError("joint frame too short")
    magic, msg_type, mask = _JOINTS_HEADER.unpack_from(buf, 0)
    if magic != MAGIC:
        raise ValueError(f"bad magic 0x{magic:02x}")
    if msg_type != MSG_JOINTS:
        raise ValueError(f"expected joints msg_type, got 0x{msg_type:02x}")
    n = bin(mask).count("1")
    expected = _JOINTS_HEADER.size + n * 2
    if len(buf) < expected:
        raise ValueError(f"joint frame too short: {len(buf)} < {expected}")
    raw = struct.unpack_from(f"<{n}h", buf, _JOINTS_HEADER.size) if n else ()
    names = []
    positions = []
    vi = 0
    for i in range(len(CANONICAL_JOINTS)):
        if mask & (1 << i):
            names.append(CANONICAL_JOINTS[i])
            positions.append(raw[vi] / _JOINT_SCALE)
            vi += 1
    return names, positions
