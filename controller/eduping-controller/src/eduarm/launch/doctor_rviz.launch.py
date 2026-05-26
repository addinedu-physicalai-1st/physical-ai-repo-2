"""doctor_rviz.launch.py — RViz 만 단독 실행 (ROS infra 와 분리).

doctor_teleop.launch.py (ROS) 와 본 launch (RViz) 를 분리해서 두 tmux 윈도우로
띄우면 RViz 만 따로 죽이거나 재시작 가능.

도커/headless 환경에서 ROS 만 띄울 때도 유리.

RViz 가 MoveIt 객체 (MotionPlanning panel 등) 를 로드하려면 robot_description /
robot_description_semantic / kinematics / planning_pipelines 파라미터가 필요 —
move_group 과 동일한 MoveItConfigsBuilder 출력 그대로 사용.
"""
from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description() -> LaunchDescription:
    moveit_config = MoveItConfigsBuilder(
        "openarm", package_name="openarm_bimanual_moveit_config"
    ).to_moveit_configs()
    moveit_params = moveit_config.to_dict()

    rviz_config = os.path.join(
        get_package_share_directory("eduarm"), "rviz", "doctor_teleop.rviz"
    )

    rviz_node = Node(
        package="rviz2",
        executable="rviz2",
        name="rviz2",
        output="screen",
        arguments=["-d", rviz_config],
        parameters=[moveit_params],
    )

    return LaunchDescription([rviz_node])
