"""OpenArm 단일 팔 8-joint 명명 — leader (openarm_mini) / follower 공통.

leader 의 joint_6 ↔ follower 의 joint_7 swap 은 leader 노드 측에서 적용해서
이 노드 들어오기 전에 이미 follower 명명규칙으로 정렬돼있다고 가정.
(lerobot openarm_mini.py 의 JOINT_REMAP 와 동일 계약)
"""
from __future__ import annotations

OPENARM_JOINT_NAMES: list[str] = [
    "joint_1",
    "joint_2",
    "joint_3",
    "joint_4",
    "joint_5",
    "joint_6",
    "joint_7",
    "gripper",
]

NUM_JOINTS: int = len(OPENARM_JOINT_NAMES)
