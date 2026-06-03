"""Binary joint passthrough codec — leader/follower 관절 스트림용 (cross-machine).

control-service ``streaming/teleop_protocol.py`` 의 MSG_JOINTS(0x03) 와 **동일 포맷**.
eduarm 은 control-service 를 import 못 하므로 같은 와이어 포맷을 여기 복제해 둔다.
한쪽 포맷을 바꾸면 반드시 양쪽을 같이 고칠 것.

JSON {"name":[...], "position":[...]} 를 대체하는 바이너리:
  관절 이름은 CANONICAL_JOINTS 고정 순서로 암시하고, 어떤 관절이 실렸는지는
  16-bit mask 로 표기 → 이름 문자열 반복 전송을 제거한다.

  magic[B]=0xDC | msg_type[B]=0x03 | mask[H]=present(16 관절)
  + int16 × popcount(mask)  (position × 10000; rad / prismatic m 공용)

16 관절 모두 실어도 4 + 32 = 36 B (JSON ~400 B 대비 1/10 이하).
"""
from __future__ import annotations

import struct

MAGIC = 0xDC
MSG_JOINTS = 0x03
_JOINT_SCALE = 10000.0  # teleop_protocol 와 동일

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
