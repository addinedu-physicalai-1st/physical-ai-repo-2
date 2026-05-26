"""leader_teleop.launch.py — fake_leader + doctor_teleop 통합.

학습용/시뮬 검증 — 실물 leader 없이 sin 모션을 leader 로 흘려보내고 follower
양팔이 sin 으로 흔드는지 확인.

흐름:
    fake_leader_node            (sin 모션 publish → /eduping/leader/joint_states)
        │
        ▼
    leader_passthrough_node     (doctor_teleop.launch.py 에 포함, joint 1:1)
        │
        ▼
    /left|right_joint_trajectory_controller/joint_trajectory
        │
        ▼
    JTC (fake_controller mock_components) → /joint_states 갱신

doctor_teleop.launch.py 의 move_group + JTC + fake_controller + RViz + relay +
leader_passthrough 모두 포함 (include 로 재사용).
"""
from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    rviz_arg = DeclareLaunchArgument("rviz", default_value="true")

    # doctor_teleop 의 ROS 인프라 그대로 재사용.
    doctor_teleop_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory("eduarm"),
                "launch",
                "doctor_teleop.launch.py",
            )
        ),
        launch_arguments={"rviz": LaunchConfiguration("rviz")}.items(),
    )

    # fake_leader: sin 모션을 /eduping/leader/joint_states 로 publish.
    # hybrid_ik 는 doctor_teleop.launch.py 가 이미 띄움 — 여기서 중복 X.
    fake_leader = Node(
        package="eduarm",
        executable="fake_leader_node",
        name="eduarm_fake_leader",
        output="screen",
    )
    delayed_fake_leader = TimerAction(period=8.0, actions=[fake_leader])

    return LaunchDescription([rviz_arg, doctor_teleop_launch, delayed_fake_leader])
