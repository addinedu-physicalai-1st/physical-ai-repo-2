"""gogoping_camera D435 + WebRTC launch.

기존 USB MJPEG launch (robot/backend/control_server 인자) 는 제거됨.
"""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        Node(
            package="gogoping_camera",
            executable="d435_webrtc_node",
            name="gogoping_camera_webrtc",
            output="screen",
            emulate_tty=True,
        ),
    ])
