"""eduping_d435_base.launch.py — EduPing D435 상시 세트 (단일 opener).

realsense2_camera(유일 D435 opener) + RGB/PointCloud/Depth bridge + 카메라 static TF.
무궁화 perception(YOLO)은 게임때만 mugunghwa.launch.py 로 별도 기동.
follower(OpenArm) 와 독립 — CAN/모터 불필요.

  ros2 launch eduarm eduping_d435_base.launch.py \
    control_url:=ws://localhost:8000 server_host:=127.0.0.1
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
        DeclareLaunchArgument("server_host", default_value="127.0.0.1"),
        DeclareLaunchArgument("server_port", default_value="8100"),
        DeclareLaunchArgument("serial_no", default_value="''"),
        # D435 mount (doctor_teleop 에서 이관). 카메라가 위 향하면 cam_pitch 음수.
        DeclareLaunchArgument("cam_pitch", default_value="0.0"),
        DeclareLaunchArgument("cam_yaw", default_value="0.0"),
        DeclareLaunchArgument("cam_roll", default_value="0.0"),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(d435_launch),
            launch_arguments={"serial_no": LaunchConfiguration("serial_no")}.items(),
        ),

        # openarm_body_link0 → d435_link (몸체 고정, arm 관절 무관 static).
        Node(
            package="tf2_ros",
            executable="static_transform_publisher",
            name="static_tf_camera_to_body",
            arguments=[
                "--x", "0.05", "--y", "0.0", "--z", "0.62",
                "--yaw", LaunchConfiguration("cam_yaw"),
                "--pitch", LaunchConfiguration("cam_pitch"),
                "--roll", LaunchConfiguration("cam_roll"),
                "--frame-id", "openarm_body_link0", "--child-frame-id", "d435_link",
            ],
            output="screen",
        ),

        Node(
            package="eduarm", executable="d435_rgb_uploader_node",
            name="d435_rgb_uploader", output="screen",
            parameters=[{"control_url": LaunchConfiguration("control_url")}],
        ),
        Node(
            package="eduarm", executable="d435_pointcloud_uploader_node",
            name="d435_pointcloud_uploader", output="screen",
            parameters=[{"control_url": LaunchConfiguration("control_url")}],
        ),
        Node(
            package="eduarm", executable="d435_depth_streamer",
            name="d435_depth_streamer", output="screen",
            parameters=[{
                "server_host": LaunchConfiguration("server_host"),
                "server_port": LaunchConfiguration("server_port"),
                "robot": "eduping",
            }],
        ),
    ])
