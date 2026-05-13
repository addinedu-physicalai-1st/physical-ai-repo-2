"""OpenArm 양팔 16-joint 명명 — leader (openarm_mini) / follower 공통.

오른팔 (can0) 8 + 왼팔 (can1) 8 = 16. lerobot openarm_mini.py 의 명명
(joint_1..joint_7, gripper) 을 left_ / right_ prefix.

URDF (bimanual openarm.urdf) joint 명과의 매핑은 OpenarmViewer.vue 의
JOINT_NAME_MAP 에서:
    right_joint_N  → openarm_right_jointN
    right_gripper  → openarm_right_finger_joint1   (joint2 는 mimic)
    left_joint_N   → openarm_left_jointN
    left_gripper   → openarm_left_finger_joint1
"""
from __future__ import annotations

OPENARM_JOINT_NAMES_RIGHT: list[str] = [
    "right_joint_1",
    "right_joint_2",
    "right_joint_3",
    "right_joint_4",
    "right_joint_5",
    "right_joint_6",
    "right_joint_7",
    "right_gripper",
]

OPENARM_JOINT_NAMES_LEFT: list[str] = [
    "left_joint_1",
    "left_joint_2",
    "left_joint_3",
    "left_joint_4",
    "left_joint_5",
    "left_joint_6",
    "left_joint_7",
    "left_gripper",
]

OPENARM_JOINT_NAMES: list[str] = OPENARM_JOINT_NAMES_RIGHT + OPENARM_JOINT_NAMES_LEFT

NUM_JOINTS: int = len(OPENARM_JOINT_NAMES)
