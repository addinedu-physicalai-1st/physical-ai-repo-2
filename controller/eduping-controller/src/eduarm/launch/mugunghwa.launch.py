"""mugunghwa.launch.py — EduPing 무궁화 device-local perception (게임때만).

카메라는 eduping_d435_base.launch.py 가 상시 제공한다. 본 launch 는 이미 떠있는
/d435/color/image_raw 를 구독하는 perception 노드만 기동 (장치 미점유).

  ros2 launch eduarm mugunghwa.launch.py device_token:=<robot device token>
"""
from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        DeclareLaunchArgument("control_url", default_value="ws://localhost:8000"),
        DeclareLaunchArgument("recognize_base_url", default_value="http://localhost:8000"),
        # dev 기본값 — control-service ROBOT_DEVICE_TOKEN / robot-web VITE_ROBOT_TOKEN 와 동일.
        DeclareLaunchArgument("device_token", default_value="dev-robot-token-change-me"),
        DeclareLaunchArgument("yolo_model", default_value="yolov8n.pt"),

        Node(
            package="eduarm",
            executable="mugunghwa_perception_node",
            name="mugunghwa_perception",
            output="screen",
            parameters=[{
                "control_url": LaunchConfiguration("control_url"),
                "recognize_base_url": LaunchConfiguration("recognize_base_url"),
                "device_token": LaunchConfiguration("device_token"),
                "yolo_model": LaunchConfiguration("yolo_model"),
            }],
        ),
    ])
