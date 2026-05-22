"""d435_depth.launch.py — EduPing 노트북에서 D435 depth+color 스트림 시작.

기본 동작:
  - 127.0.0.1:8100 (로컬 control-service streaming 프로세스) 로 송출
  - 320×240 @ 10fps

원격 서버로 송출 시:
  ros2 launch eduarm d435_depth.launch.py server_host:=10.0.0.5
"""
from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        DeclareLaunchArgument("server_host", default_value="127.0.0.1"),
        DeclareLaunchArgument("server_port", default_value="8100"),
        DeclareLaunchArgument("robot", default_value="eduping"),
        DeclareLaunchArgument("width", default_value="424"),
        DeclareLaunchArgument("height", default_value="240"),
        DeclareLaunchArgument("fps", default_value="15"),
        DeclareLaunchArgument("jpeg_quality", default_value="70"),
        DeclareLaunchArgument("log_level", default_value="INFO"),

        Node(
            package="eduarm",
            executable="d435_depth_streamer",
            name="d435_depth_streamer",
            output="screen",
            arguments=[
                "--server-host", LaunchConfiguration("server_host"),
                "--server-port", LaunchConfiguration("server_port"),
                "--robot", LaunchConfiguration("robot"),
                "--width", LaunchConfiguration("width"),
                "--height", LaunchConfiguration("height"),
                "--fps", LaunchConfiguration("fps"),
                "--jpeg-quality", LaunchConfiguration("jpeg_quality"),
                "--log-level", LaunchConfiguration("log_level"),
            ],
        ),
    ])
