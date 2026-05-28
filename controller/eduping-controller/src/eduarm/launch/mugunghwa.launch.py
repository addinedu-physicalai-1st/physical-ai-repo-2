"""mugunghwa.launch.py — EduPing 무궁화 device-local perception.

D435 camera + mugunghwa_perception_node 동시 기동. control-service 가 떠 있어야
WS producer 가 붙고, recognize-multi(InsightFace) 호출이 성공한다.

  ros2 launch eduarm mugunghwa.launch.py device_token:=<robot device token>
원격 control-service:
  ros2 launch eduarm mugunghwa.launch.py control_url:=ws://10.0.0.5:8000 \
       recognize_base_url:=http://10.0.0.5:8000 device_token:=<token>
"""
from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    eduarm_share = get_package_share_directory("eduarm")
    d435_launch = os.path.join(eduarm_share, "launch", "d435_camera.launch.py")

    return LaunchDescription([
        DeclareLaunchArgument("control_url", default_value="ws://localhost:8000"),
        DeclareLaunchArgument("recognize_base_url", default_value="http://localhost:8000"),
        DeclareLaunchArgument("device_token", default_value=""),
        DeclareLaunchArgument("yolo_model", default_value="yolov8n.pt"),

        IncludeLaunchDescription(PythonLaunchDescriptionSource(d435_launch)),

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
