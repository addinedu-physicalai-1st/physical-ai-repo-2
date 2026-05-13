"""sim_only.launch.py — 실물 하드웨어 없이 녹화/재생 파이프라인 검증용.

띄움:
  - fake_leader_node : /eduping/leader/joint_states (50Hz 합성)
  - sim_twin_node    : /eduping/joint_trajectory → /joint_states (50Hz forward)

이 launch 와 함께 FastAPI control server (eduping bridge 활성) 를 띄우고
robot UI 의 OpenarmViewer 를 열면 fake leader 의 사인파 모션이 three.js 에
바로 보인다. recorder 시작/중지 + player 재생 검수도 이 조합에서 가능.

실물 모드에서는 본 launch 대신 openarm_bringup + (추후) feetech_leader 를 띄움.
"""
from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        DeclareLaunchArgument("leader_topic", default_value="/eduping/leader/joint_states"),
        DeclareLaunchArgument("trajectory_topic", default_value="/eduping/joint_trajectory"),
        DeclareLaunchArgument("joint_states_topic", default_value="/joint_states"),
        DeclareLaunchArgument("rate_hz", default_value="50.0"),
        DeclareLaunchArgument("amplitude", default_value="0.5"),
        DeclareLaunchArgument("period_s", default_value="6.0"),

        Node(
            package="pingdergarten_openarm",
            executable="fake_leader_node",
            name="fake_leader_node",
            output="screen",
            parameters=[{
                "topic": LaunchConfiguration("leader_topic"),
                "rate_hz": LaunchConfiguration("rate_hz"),
                "amplitude": LaunchConfiguration("amplitude"),
                "period_s": LaunchConfiguration("period_s"),
            }],
        ),
        Node(
            package="pingdergarten_openarm",
            executable="sim_twin_node",
            name="sim_twin_node",
            output="screen",
            parameters=[{
                "input_topic": LaunchConfiguration("trajectory_topic"),
                "output_topic": LaunchConfiguration("joint_states_topic"),
                "publish_hz": LaunchConfiguration("rate_hz"),
            }],
        ),
    ])
