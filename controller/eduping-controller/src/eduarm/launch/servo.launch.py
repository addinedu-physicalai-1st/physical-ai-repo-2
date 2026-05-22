"""servo.launch.py — MoveIt Servo 노드 (왼팔 / 오른팔 선택).

Phase 3 의 안전 가드 (planning-scene octomap 과 ≤ 4cm 근접 시 halt) 가 여기서 활성화.
twist 입력 publisher 는 Phase 4 의 servo_reach_node 가 담당.

인자:
  arm:=left | right                    (default left)
  command_out_topic:=<topic>           sim 환경 sim_twin 으로 들어가려면 /eduping/joint_trajectory,
                                       실 ros2_control 환경엔 /left_arm_controller/joint_trajectory.

설계 메모:
  · servo.yaml 은 그대로 dict 화해서 parameters=[{"moveit_servo": dict}] 형태로 주입.
    --params-file 로 안 거는 이유: 파일 안에 `ros__parameters:` wrapper 없이 flat
    구조로 두면 (panda 예제 따름) launch 가 prefix 를 알아서 붙여줘서 가장 깔끔.

사용 예:
  # sim (sim_twin 으로 흐름):
  ros2 launch eduarm servo.launch.py arm:=left

  # 실 (ros2_control):
  ros2 launch eduarm servo.launch.py arm:=left \\
       command_out_topic:=/left_arm_controller/joint_trajectory

검증:
  ros2 service call /servo_node/start_servo std_srvs/srv/Trigger
  ros2 topic pub -r 50 /servo_node/delta_twist_cmds geometry_msgs/msg/TwistStamped \\
       "{header: {frame_id: world}, twist: {linear: {x: 0.02}}}"
"""
from __future__ import annotations

import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder


def _spawn(context, *args, **kwargs):
    arm = LaunchConfiguration("arm").perform(context)
    command_out_topic = LaunchConfiguration("command_out_topic").perform(context)
    if arm not in ("left", "right"):
        raise RuntimeError(f"arm 은 left 또는 right — got {arm!r}")

    eduarm_share = get_package_share_directory("eduarm")
    servo_yaml_path = os.path.join(eduarm_share, "config", "servo.yaml")
    sensors_3d_yaml = os.path.join(eduarm_share, "config", "sensors_3d.yaml")

    with open(servo_yaml_path) as f:
        servo_params = yaml.safe_load(f)
    # arm 선택 + sim/real topic 분기 override.
    servo_params["move_group_name"] = f"{arm}_arm"
    servo_params["command_out_topic"] = command_out_topic

    # sensors_3d.yaml 을 같이 주입해야 servo 의 collision check 가 보는 planning scene
    # (octomap 포함) 이 octomap_demo.launch.py 가 띄운 move_group 의 것과 동일하게
    # 정렬됨. servo 는 monitored_planning_scene listener 라 planner 자체는 안 가지지만
    # ROS param 의 robot_description / SRDF / kinematics 가 일치해야 IK + collision 모델
    # 이 같다.
    moveit_config = (
        MoveItConfigsBuilder("openarm", package_name="openarm_bimanual_moveit_config")
        .sensors_3d(file_path=sensors_3d_yaml)
        .to_moveit_configs()
    )

    return [
        Node(
            package="moveit_servo",
            executable="servo_node",
            name="servo_node",
            output="screen",
            parameters=[
                moveit_config.robot_description,
                moveit_config.robot_description_semantic,
                moveit_config.robot_description_kinematics,
                moveit_config.joint_limits,
                # moveit_servo prefix 아래에 flat servo params 묶음 주입.
                {"moveit_servo": servo_params},
            ],
        ),
    ]


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        DeclareLaunchArgument("arm", default_value="left",
                              description="left | right — servo 할 팔."),
        DeclareLaunchArgument(
            "command_out_topic",
            default_value="/eduping/joint_trajectory",
            description="Servo 출력 trajectory 토픽. sim_twin (sim) 또는 "
                        "/{arm}_arm_controller/joint_trajectory (real) 로 override.",
        ),
        OpaqueFunction(function=_spawn),
    ])
