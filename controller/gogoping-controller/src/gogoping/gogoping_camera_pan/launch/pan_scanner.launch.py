"""Launch the auto-sweep pan_scanner alongside servo_bridge.

Conflicts with keyboard_teleop — only run one publisher to /cmd_pan at a time.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    pkg_share = get_package_share_directory('gogoping_camera_pan')
    params = os.path.join(pkg_share, 'config', 'params.yaml')

    return LaunchDescription([
        Node(
            package='gogoping_camera_pan',
            executable='servo_bridge',
            name='servo_bridge',
            parameters=[params],
            output='screen',
        ),
        Node(
            package='gogoping_camera_pan',
            executable='pan_scanner',
            name='pan_scanner',
            parameters=[params],
            output='screen',
        ),
    ])
