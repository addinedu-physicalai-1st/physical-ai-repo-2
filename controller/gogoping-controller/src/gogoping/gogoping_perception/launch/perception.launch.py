from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        Node(
            package="gogoping_perception",
            executable="perception_node",
            name="gogoping_perception_node",
            output="screen",
        ),
    ])
