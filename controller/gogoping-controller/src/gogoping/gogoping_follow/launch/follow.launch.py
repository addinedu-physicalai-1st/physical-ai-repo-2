"""ros2 launch gogoping_follow follow.launch.py"""
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        Node(
            package="gogoping_follow",
            executable="follow_node",
            name="gogoping_follow_node",
            output="screen",
        ),
    ])
