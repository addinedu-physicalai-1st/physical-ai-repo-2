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
    control_url = LaunchConfiguration("control_url")
    return LaunchDescription([
        DeclareLaunchArgument("fake", default_value="false"),
        # udev 심볼릭 (99-eduping-stethoscope.rules) — /dev/ttyACM* 가 바뀌어도 고정.
        DeclareLaunchArgument("serial_port", default_value="/dev/eduping_stetho"),
        # FSR WS uploader 가 control 서버로 push — 2-머신(a-2)이면 의사 머신 IP.
        DeclareLaunchArgument("control_url", default_value="ws://localhost:8000"),
        Node(
            package="eduping_stethoscope",
            executable="fsr_bridge_node",
            name="fsr_bridge_node",
            output="screen",
            parameters=[params, {"fake": fake, "serial_port": serial_port}],
        ),
        # ROS sub → WebSocket. ROS DDS 로 cross-machine 안 보내고 control 서버로 직접 push.
        Node(
            package="eduping_stethoscope",
            executable="fsr_ws_uploader_node",
            name="fsr_ws_uploader",
            output="screen",
            parameters=[{"control_url": control_url}],
        ),
    ])
