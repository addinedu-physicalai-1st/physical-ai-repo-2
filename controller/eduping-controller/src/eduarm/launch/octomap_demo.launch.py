"""octomap_demo.launch.py — Phase 1+2+3 end-to-end (실하드웨어).

띄움:
  1. d435_camera.launch.py        — realsense2_camera (ROS 토픽 publish)
  2. robot_state_publisher        — URDF 기반 TF (d435_depth_optical_frame 포함)
  3. move_group                   — MoveIt + OccupancyMapMonitor (sensors_3d.yaml 주입)
  4. sim_twin_node                — /eduping/joint_trajectory → /joint_states (실팔 없을 때 동작)
  5. servo_node (Phase 3)         — left_arm cartesian-velocity 제어. check_collisions=true
                                     로 octomap voxel 과 ≤4cm 근접 시 halt.
  6. RViz                         — octomap.rviz 자동 로드

인자:
  servo_arm:=left | right                          (default left)
  servo_out:=<topic>                               servo 출력 trajectory.
        real ros2_control 면 /{arm}_arm_controller/joint_trajectory,
        sim_twin 으로 보려면 /eduping/joint_trajectory.
        default 가 real-controller 경로 (이 launch 가 real 용이므로).

검증:
  T1) sudo apt install ros-jazzy-realsense2-camera ros-jazzy-realsense2-description \\
                       ros-jazzy-moveit-servo ros-jazzy-octomap-rviz-plugins
  T2) cd controller/eduping-controller && colcon build --symlink-install && source install/setup.bash
  T3) ros2 launch eduarm octomap_demo.launch.py
       (move_group KDL 로딩 1-2초 + realsense2_camera 초기화 1-3초 + servo init)
  T4) RViz 의 OctoMap display 가 켜진 채로 D435 앞에 손 흔들기 → octomap voxel 채워짐
  T5) ros2 service call /servo_node/start_servo std_srvs/srv/Trigger
       ros2 topic pub -r 50 /servo_node/delta_twist_cmds geometry_msgs/msg/TwistStamped \\
            "{header: {frame_id: world}, twist: {linear: {x: 0.02}}}"
       팔이 X+ 로 천천히 움직임. D435 시야에 손을 가져다 대면 octomap 채워지고 servo 가
       'Halting for collision' 로그 + 정지.

Phase 4 (twist driver: 'high-five reach' 등) 는 후속.
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

    # sensors_3d.yaml 을 명시적으로 주입해서 OccupancyMapMonitor 가 D435 depth 를
    # 읽도록 한다. openarm_bimanual_moveit_config 안의 sensors_3d.yaml 은 kinect
    # placeholder 라 사용 안 함 (그쪽은 submodule 이라 직접 수정하지 않고 overlay).
    moveit_config = (
        MoveItConfigsBuilder("openarm", package_name="openarm_bimanual_moveit_config")
        .sensors_3d(file_path=sensors_3d_path)
        .to_moveit_configs()
    )
    moveit_params = moveit_config.to_dict()

    # OccupancyMapMonitor 활성화에 필요한 명시 파라미터 — sensors_3d.yaml 만으론
    # 일부 버전의 MoveIt 가 monitor 를 실제 spawn 하지 않는 케이스가 있어 함께 박는다.
    octomap_params = {
        "octomap_frame": "world",
        "octomap_resolution": 0.02,   # 2 cm. 너무 작으면 갱신 비용↑.
        "max_range": 3.0,
    }

    rsp_params = {"robot_description": moveit_params["robot_description"]}

    return LaunchDescription([
        DeclareLaunchArgument("servo_arm", default_value="left",
                              description="MoveIt Servo 가 제어할 팔 (left | right)."),
        DeclareLaunchArgument(
            "servo_out", default_value="/left_arm_controller/joint_trajectory",
            description="Servo 출력 trajectory 토픽. 본 launch 는 real-hardware 용이라 "
                        "ros2_control trajectory controller 의 표준 토픽을 default 로.",
        ),

        # 1) D435 → ROS topics (realsense2_camera include)
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(eduarm_share, "launch", "d435_camera.launch.py"),
            ),
        ),

        # 2) URDF TF
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="robot_state_publisher",
            output="screen",
            parameters=[rsp_params],
        ),

        # 3) MoveIt move_group (planning scene + OccupancyMapMonitor)
        Node(
            package="moveit_ros_move_group",
            executable="move_group",
            name="move_group",
            output="screen",
            parameters=[moveit_params, octomap_params],
        ),

        # 4) 실팔 없을 때도 /joint_states 가 흘러야 TF + octomap pose 계산이 가능.
        Node(
            package="eduarm",
            executable="sim_twin_node",
            name="sim_twin_node",
            output="screen",
        ),

        # 5) servo_node (Phase 3) — collision-aware cartesian-velocity.
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(servo_launch),
            launch_arguments={
                "arm": LaunchConfiguration("servo_arm"),
                "command_out_topic": LaunchConfiguration("servo_out"),
            }.items(),
        ),

        # 6) servo_reach_node (Phase 4) — PointStamped target → TwistStamped.
        Node(
            package="eduarm",
            executable="servo_reach_node",
            name="servo_reach_node",
            output="screen",
            parameters=[{"arm": LaunchConfiguration("servo_arm")}],
        ),

        # 7) RViz — octomap display + MotionPlanning panel 자동 로드.
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
