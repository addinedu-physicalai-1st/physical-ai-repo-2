"""eduping_d435_base.launch.py — EduPing D435 상시 세트 (단일 opener).

realsense2_camera(유일 D435 opener) + RGB/PointCloud/Depth bridge + 카메라 static TF
+ 무궁화 perception 노드. follower(OpenArm) 와 독립 — CAN/모터 불필요.

perception 노드는 항상 떠 있되 idle 에선 YOLO 를 돌리지 않는다. robot-web 가 무궁화
모드에 진입(/ws/eduping/mugunghwa role=ui)하면 relay 가 peer present=true 를 보내
노드가 entry 로 전환되며 그때부터 YOLO 추론 시작, 모드 이탈 시 다시 idle. 즉 무거운
추론은 UI 가 켜고 끈다 — 별도 기동 단계 불필요.

  ros2 launch eduarm eduping_d435_base.launch.py \
    control_url:=ws://localhost:8000 server_host:=127.0.0.1 device_token:=<robot-token>
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
        # dev 기본값 — control-service ROBOT_DEVICE_TOKEN / robot-web VITE_ROBOT_TOKEN 와 동일.
        DeclareLaunchArgument("device_token", default_value="dev-robot-token-change-me"),
        DeclareLaunchArgument("yolo_model", default_value="yolov8n.pt"),
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
        # 근접 안전정지 — YOLO 사람 검출 + aligned depth 로 사람이 0.6m 이내인지 감지 →
        # /eduping/proximity_block. 사람 게이트라 로봇 자기 팔/바닥은 트리거 안 함. 전역(모든
        # 팔 동작)에 적용: bridge 가 받아 팔 정지/재개, robot-web 이 음악 정지/재개.
        Node(
            package="eduarm", executable="proximity_safety_node",
            name="proximity_safety", output="screen",
            parameters=[{"yolo_model": LaunchConfiguration("yolo_model")}],
        ),
        # 무궁화 perception — 항상 실행, idle 에선 YOLO 미가동. robot-web 무궁화 모드
        # 진입 시 relay 의 peer 이벤트로 entry 전환되어 추론 시작 (UI 가 켜고 끈다).
        Node(
            package="eduarm", executable="mugunghwa_perception_node",
            name="mugunghwa_perception", output="screen",
            parameters=[{
                "control_url": LaunchConfiguration("control_url"),
                "recognize_base_url": LaunchConfiguration("recognize_base_url"),
                "device_token": LaunchConfiguration("device_token"),
                "yolo_model": LaunchConfiguration("yolo_model"),
            }],
        ),
    ])
