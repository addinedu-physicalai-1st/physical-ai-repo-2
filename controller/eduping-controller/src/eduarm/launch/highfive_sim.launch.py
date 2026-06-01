"""highfive_sim.launch.py — sim 환경에서 high-five 파이프라인 검증.

띄움:
  - robot_state_publisher (openarm bimanual URDF) — TF tree (d435_depth_optical_frame 포함)
  - move_group (MoveIt + TRAC-IK + sensors_3d) — /compute_ik + octomap planning scene
  - sim_twin_node — /eduping/joint_trajectory → /joint_states (50Hz, 마지막 frame hold)
  - highfive_node — /eduping/highfive/hand_point 수신 + collision-aware IK +
    quintic 다중 waypoint JointTrajectory publish

검증:
  T1) ros2 launch eduarm d435_camera.launch.py   (D435 → /d435/depth/* 토픽; sensors_3d 가 소비)
  T2) ros2 launch eduarm highfive_sim.launch.py  (MoveIt + highfive_node)
  T3) scripts/run_control.sh
  T4) curl -X POST http://localhost:8000/api/eduping/highfive/hand-target \\
        -H 'content-type: application/json' \\
        -d '{"x": 0.0, "y": 0.0, "z": 0.5}'
       → highfive_node 가 scripted gesture trajectory publish
  T5) ros2 topic echo /eduping/joint_trajectory  (trajectory 도착 확인)
  T6) robot-web → EduPing → 관리 → 뎁스카메라 뷰
"""
from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description() -> LaunchDescription:
    # KDL default 는 OpenArm 7-DOF reach envelope 을 너무 좁게 잡아 TRAC-IK 로 override
    # (eduarm/config/kinematics_trac_ik.yaml). 설치: `apt install ros-jazzy-trac-ik-kinematics-plugin`.
    # highfive_node 는 scripted gesture 라 IK 직접 호출 안 함 — TRAC-IK 는 move_group 의
    # FK / collision query 경로에서만 사용.
    eduarm_share = get_package_share_directory("eduarm")
    trac_ik_yaml = os.path.join(eduarm_share, "config", "kinematics_trac_ik.yaml")
    moveit_config = (
        MoveItConfigsBuilder("openarm", package_name="openarm_bimanual_moveit_config")
        .robot_description_kinematics(file_path=trac_ik_yaml)
        .to_moveit_configs()
    )
    moveit_params = moveit_config.to_dict()
    # move_group 와 동일 URDF — TF (world, d435_depth_optical_frame, 양팔) 일치.
    rsp_params = {
        "robot_description": moveit_params["robot_description"],
    }

    return LaunchDescription([
        DeclareLaunchArgument(
            "mujoco", default_value="false",
            description="true → MuJoCo physics+viewer (mujoco_twin_node); "
                        "false (default) → lightweight sim_twin_node (no window).",
        ),
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
            parameters=[moveit_params],
        ),
        # sim twin: joint_trajectory → /joint_states. DEFAULT = lightweight sim_twin
        # (no MuJoCo — 시뮬 데모 종료). mujoco:=true → MuJoCo physics+viewer
        # (mujoco_twin_node, scripts/show_mujoco_highfive.sh 가 이 인자로 띄움). 둘 다
        # node name 'sim_twin_node' + topic 동일 (drop-in); 동시에 뜨면 /joint_states
        # 충돌하므로 IfCondition/UnlessCondition 으로 정확히 하나만 활성화.
        Node(
            package="eduarm",
            executable="sim_twin_node",
            name="sim_twin_node",
            output="screen",
            condition=UnlessCondition(LaunchConfiguration("mujoco")),
        ),
        Node(
            package="eduarm",
            executable="mujoco_twin_node",
            name="sim_twin_node",
            output="screen",
            condition=IfCondition(LaunchConfiguration("mujoco")),
        ),
        Node(
            package="eduarm",
            executable="highfive_node",
            name="highfive_node",
            output="screen",
        ),
        # depth_mask_node — hand_point 주변 sphere 0 으로 mask → octomap 가 손을
        # obstacle 로 안 봄. IK 가 손 위치까지 도달 가능 + 그 외 body/배경 회피.
        Node(
            package="eduarm",
            executable="depth_mask_node",
            name="depth_mask_node",
            output="screen",
        ),
    ])
