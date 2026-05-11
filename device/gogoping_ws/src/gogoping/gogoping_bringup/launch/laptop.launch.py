"""GogoPing 노트북용 bringup launch.

추후 단계:
- Nav2 (gogoping_navigation/launch/...)
- gogoping_modes (FSM + Behavior Tree 메인 노드)
- gogoping_vision (얼굴 인식 / 사람 추종)

현재는 placeholder — 실제 통합 시 채워진다.
"""

from launch import LaunchDescription
from launch.actions import LogInfo


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        LogInfo(msg="[gogoping_bringup] laptop.launch.py — TODO: Nav2 + modes + vision"),
    ])
