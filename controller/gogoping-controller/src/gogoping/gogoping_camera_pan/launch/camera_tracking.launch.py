"""Launch — gogoping_camera_pan.auto_tracker (bbox -> servo commands)."""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        Node(
            package='gogoping_camera_pan',
            executable='auto_tracker',
            name='gogoping_camera_auto_tracker',
            output='screen',
            emulate_tty=True,
        ),
    ])
