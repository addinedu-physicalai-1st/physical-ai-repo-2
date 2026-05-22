"""highfive_sim.launch.py — sim 환경에서 high-five 파이프라인 검증.

띄움:
  - robot_state_publisher (openarm bimanual URDF) — TF tree (d435_depth_optical_frame 포함)
  - move_group (MoveIt) — /compute_ik 서비스 제공
  - sim_twin_node — /eduping/joint_trajectory → /joint_states (50Hz, 마지막 frame hold)
  - highfive_node — /eduping/highfive/hand_point 수신 + IK + JointTrajectory publish

검증:
  T1) ros2 launch eduarm highfive_sim.launch.py
       (move_group 가 KDL solver 로드되면서 1-2초 걸림)
  T2) scripts/run_server.sh
  T3) curl -X POST http://localhost:8000/api/eduping/highfive/hand-target \
        -H 'content-type: application/json' \
        -d '{"x": 0.0, "y": 0.0, "z": 0.5}'
       → highfive_node 가 IK 시도, success 시 JointTrajectory publish
  T4) ros2 topic echo /eduping/joint_trajectory  (trajectory 도착 확인)
  T5) robot-web → EduPing → 뎁스카메라 뷰 → ✋ 하이파이브 ON → 손 0.3~1.5m
       (또는 scripts/dev-eduping-highfive-sim.sh 로 T1 단독 실행)

OpenarmViewer 는 /joint_states 를 직접 읽지 않음 — control-service WS 가 forward.
모션이 안 보이면 sim_twin_node /joint_states 출력 + control bridge 가 살아있는지 확인.
"""
from __future__ import annotations

from launch import LaunchDescription
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description() -> LaunchDescription:
    moveit_config = MoveItConfigsBuilder(
        "openarm", package_name="openarm_bimanual_moveit_config",
    ).to_moveit_configs()
    moveit_params = moveit_config.to_dict()
    # move_group 와 동일 URDF — TF (world, d435_depth_optical_frame, 양팔) 일치.
    rsp_params = {
        "robot_description": moveit_params["robot_description"],
    }

    return LaunchDescription([
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
        Node(
            package="eduarm",
            executable="sim_twin_node",
            name="sim_twin_node",
            output="screen",
        ),
        Node(
            package="eduarm",
            executable="highfive_node",
            name="highfive_node",
            output="screen",
        ),
    ])
