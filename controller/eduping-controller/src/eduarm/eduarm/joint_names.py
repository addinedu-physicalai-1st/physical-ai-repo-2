"""OpenArm 양팔 16-joint 명명 — leader / follower / URDF 공통.

오른팔 (can0) 8 + 왼팔 (can1) 8 = 16. 이름은 모두 `openarm_description`
URDF 와 일치 — 변환 레이어 없이 실물 ros2_control 컨트롤러 + UI three.js
viewer 가 동일 키를 사용한다.

레퍼런스 (openarm.urdf):
    openarm_{right|left}_joint1 .. joint7    revolute
    openarm_{right|left}_finger_joint1       prismatic (joint2 는 mimic)
"""
from __future__ import annotations

OPENARM_JOINT_NAMES_RIGHT: list[str] = [
    "openarm_right_joint1",
    "openarm_right_joint2",
    "openarm_right_joint3",
    "openarm_right_joint4",
    "openarm_right_joint5",
    "openarm_right_joint6",
    "openarm_right_joint7",
    "openarm_right_finger_joint1",
]

OPENARM_JOINT_NAMES_LEFT: list[str] = [
    "openarm_left_joint1",
    "openarm_left_joint2",
    "openarm_left_joint3",
    "openarm_left_joint4",
    "openarm_left_joint5",
    "openarm_left_joint6",
    "openarm_left_joint7",
    "openarm_left_finger_joint1",
]

OPENARM_JOINT_NAMES: list[str] = OPENARM_JOINT_NAMES_RIGHT + OPENARM_JOINT_NAMES_LEFT

NUM_JOINTS: int = len(OPENARM_JOINT_NAMES)

# 양팔 home pose — 모든 joint zero, gripper close. 율동 정지 시 복귀 목표.
# 순서: OPENARM_JOINT_NAMES 와 동일 (right 1..7 + r-finger + left 1..7 + l-finger).
HOME_POSE: list[float] = [0.0] * NUM_JOINTS

# Home 복귀 trapezoidal velocity profile 한계.
# 가장 큰 delta 가진 joint 가 v_max 로 cruise, a_max 로 가속/감속. 다른 joint 은 같은
# 시간 안에서 time-scaled 선형 (작은 delta → 작은 속도). 시작·끝 속도 0 → 부드러움.
HOME_V_MAX: float = 0.5  # rad/s (≈ 28.6°/s)
HOME_A_MAX: float = 1.0  # rad/s² (≈ 57.3°/s²) — v_max 도달까지 0.5s
