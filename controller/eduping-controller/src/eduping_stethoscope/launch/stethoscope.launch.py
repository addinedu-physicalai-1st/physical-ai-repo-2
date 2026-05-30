import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    params = os.path.join(
        get_package_share_directory("eduping_stethoscope"), "config", "params.yaml"
    )
    fake = LaunchConfiguration("fake")
    serial_port = LaunchConfiguration("serial_port")
    return LaunchDescription([
        DeclareLaunchArgument("fake", default_value="false"),
        # udev 심볼릭 (99-eduping-stethoscope.rules) — /dev/ttyACM* 가 바뀌어도 고정.
        DeclareLaunchArgument("serial_port", default_value="/dev/eduping_stetho"),
        Node(
            package="eduping_stethoscope",
            executable="fsr_bridge_node",
            name="fsr_bridge_node",
            output="screen",
            parameters=[params, {"fake": fake, "serial_port": serial_port}],
        ),
    ])
