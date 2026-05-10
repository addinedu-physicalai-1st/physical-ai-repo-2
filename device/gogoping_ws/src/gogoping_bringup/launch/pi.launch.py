"""GogoPing Raspberry Pi 진입점 launch.

라파에서 띄울 모든 hw 노드 통합:
  1. vic_pinky_namespaced — vic_pinky vendor 를 'gogoping' namespace 로 wrap
                             (모터 드라이버 + RPLiDAR + robot_state_publisher)
  2. gogoping_camera_pan  — pyserial → Arduino 서보 (pan / 추후 tilt)

사용:
    ros2 launch gogoping_bringup pi.launch.py
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description() -> LaunchDescription:
    namespaced_share = get_package_share_directory('vic_pinky_namespaced')
    camera_pan_share = get_package_share_directory('gogoping_camera_pan')

    vic_pinky_ns = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(namespaced_share, 'launch', 'gogoping_bringup.launch.py')
        ),
    )

    camera_pan = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(camera_pan_share, 'launch', 'camera_pan.launch.py')
        ),
    )

    return LaunchDescription([
        vic_pinky_ns,
        camera_pan,
    ])
