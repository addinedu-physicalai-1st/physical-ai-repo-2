"""octomap_demo_sim.launch.py — Phase 1+2+3 wiring 검증 (실 D435 없을 때).

octomap_demo.launch.py 와 동일하지만 d435_camera.launch.py 만 빠진다. 따라서:
  - robot_state_publisher, move_group, sim_twin_node, servo_node, RViz 모두 정상 기동
  - OccupancyMapMonitor 도 spawn 되지만 /d435/depth/image_rect_raw 가 안 와서
    octomap voxel 은 비어 있음 (Phase 4 의 fake-depth publisher 가 후속)
  - servo_node 는 sim_twin 으로 출력 (/eduping/joint_trajectory) — sim 에서도 twist
    명령에 따라 three.js 뷰어가 움직임. octomap 이 비어있으니 충돌 가드는 self-collision
    만 동작.

목적: 실 D435 없이 servo + planner + sim_twin 까지 build/launch 흐름 검증.

인자:
  servo_arm:=left | right    (default left)

검증:
  T1) ros2 launch eduarm octomap_demo_sim.launch.py
  T2) ros2 service call /servo_node/start_servo std_srvs/srv/Trigger
       ros2 topic pub -r 50 /servo_node/delta_twist_cmds geometry_msgs/msg/TwistStamped \\
            "{header: {frame_id: world}, twist: {linear: {x: 0.02}}}"
       three.js 뷰어의 왼팔이 X+ 로 천천히 움직임.
"""
from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description() -> LaunchDescription:
    eduarm_share = get_package_share_directory("eduarm")
    sensors_3d_path = os.path.join(eduarm_share, "config", "sensors_3d.yaml")
    rviz_config = os.path.join(eduarm_share, "rviz", "octomap.rviz")
    servo_launch = os.path.join(eduarm_share, "launch", "servo.launch.py")

    moveit_config = (
        MoveItConfigsBuilder("openarm", package_name="openarm_bimanual_moveit_config")
        .sensors_3d(file_path=sensors_3d_path)
        .to_moveit_configs()
    )
    moveit_params = moveit_config.to_dict()

    octomap_params = {
        "octomap_frame": "world",
        "octomap_resolution": 0.02,
        "max_range": 3.0,
    }

    rsp_params = {"robot_description": moveit_params["robot_description"]}

    return LaunchDescription([
        DeclareLaunchArgument("servo_arm", default_value="left",
                              description="MoveIt Servo 가 제어할 팔 (left | right)."),

        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="robot_state_publisher",
            output="screen",
            parameters=[rsp_params],
        ),
        Node(
            package="moveit_ros_move_group",
            executable="move_group",
            name="move_group",
            output="screen",
            parameters=[moveit_params, octomap_params],
        ),
        Node(
            package="eduarm",
            executable="sim_twin_node",
            name="sim_twin_node",
            output="screen",
        ),

        # Phase 3 servo — sim_twin 으로 출력해서 three.js 뷰어가 움직이도록.
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(servo_launch),
            launch_arguments={
                "arm": LaunchConfiguration("servo_arm"),
                "command_out_topic": "/eduping/joint_trajectory",
            }.items(),
        ),

        # Phase 4 driver — PointStamped target → TwistStamped.
        Node(
            package="eduarm",
            executable="servo_reach_node",
            name="servo_reach_node",
            output="screen",
            parameters=[{"arm": LaunchConfiguration("servo_arm")}],
        ),

        Node(
            package="rviz2",
            executable="rviz2",
            name="rviz2",
            output="screen",
            arguments=["-d", rviz_config],
            parameters=[
                {"robot_description": moveit_params["robot_description"]},
                {"robot_description_semantic": moveit_params["robot_description_semantic"]},
            ],
        ),
    ])
