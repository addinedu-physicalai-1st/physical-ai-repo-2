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
        Node(
            package="gogoping_perception",
            executable="safety_monitor",
            name="gogoping_safety_monitor",
            output="screen",
            emulate_tty=True,
        ),
        Node(
            package="gogoping_perception",
            executable="safety_filter",
            name="gogoping_safety_filter",
            output="screen",
            emulate_tty=True,
        ),
    ])
