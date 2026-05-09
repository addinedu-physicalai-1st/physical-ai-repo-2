"""NoriArm 게임 프레임워크.

매니페스트 (`games/<name>/game.yaml`) 로 게임당 필요한 카메라·OMX 팔·정책 종류를
선언하면, 런처가 매니페스트를 읽어 ROS2 launch description 을 합성하고 정책 루프를
시작한다. rule_based / smolvla 정책이 같은 게임 루프 코드 위에서 교체 가능하다.

Public API:
    Policy, Observation, Action  — 정책 인터페이스
    GameConfig, load_manifest    — 매니페스트 로딩
"""
from noriarm_framework.manifest import GameConfig, load_manifest
from noriarm_framework.policy import Action, Observation, Policy

__all__ = [
    "Action",
    "GameConfig",
    "Observation",
    "Policy",
    "load_manifest",
]
