"""follower_bimanual.launch.py — OpenArm 양팔 follower bringup (RViz 제외).

upstream `openarm_bringup/launch/openarm.bimanual.launch.py` 의 동작을 1:1 재구현 —
robot_state_publisher · controller_manager · joint_state_broadcaster · arm /
gripper controller spawner 만 띄우고 **RViz 는 띄우지 않음**. robot-web 의 three.js
viewer 가 시각화를 담당.

upstream 의 robot_description / controller config 경로는 그대로 참조 (xacro + 컨트롤러
YAML 모두 openarm_description / openarm_bringup 패키지에서 가져옴).

ros2 launch eduarm follower_bimanual.launch.py
  arm_type:=v10
  hardware_type:=real          (use_fake_hardware 매핑 — real→false, mock→true)
  right_can_interface:=can0
  left_can_interface:=can1
"""
import os

import xacro
from ament_index_python.packages import get_package_share_directory

from launch import LaunchContext, LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction, TimerAction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


# 컨트롤러 매니저 spawner 가 호출하는 controller_manager 노드 이름 — 본 launch 는
# namespace 미사용 (단일 controller_manager) 이라 항상 '/controller_manager'.
CONTROLLER_MANAGER_REF = "/controller_manager"


def _generate_robot_description(
    context: LaunchContext,
    description_package, description_file, arm_type,
    use_fake_hardware, right_can_interface, left_can_interface,
) -> str:
    """xacro 처리 — upstream generate_robot_description 과 동일."""
    description_package_str = context.perform_substitution(description_package)
    description_file_str = context.perform_substitution(description_file)
    arm_type_str = context.perform_substitution(arm_type)
    use_fake_hardware_str = context.perform_substitution(use_fake_hardware)
    right_can_interface_str = context.perform_substitution(right_can_interface)
    left_can_interface_str = context.perform_substitution(left_can_interface)

    xacro_path = os.path.join(
        get_package_share_directory(description_package_str),
        "urdf", "robot", description_file_str,
    )
    robot_description = xacro.process_file(
        xacro_path,
        mappings={
            "arm_type": arm_type_str,
            "bimanual": "true",
            "use_fake_hardware": use_fake_hardware_str,
            "ros2_control": "true",
            "right_can_interface": right_can_interface_str,
            "left_can_interface": left_can_interface_str,
        },
    ).toprettyxml(indent="  ")
    return robot_description


def _robot_and_control_nodes(context: LaunchContext, *args):
    """robot_state_publisher + ros2_control_node 띄움. upstream robot_nodes_spawner 와 동일."""
    (description_package, description_file, arm_type, use_fake_hardware,
     controllers_file, right_can_interface, left_can_interface) = args

    robot_description = _generate_robot_description(
        context, description_package, description_file, arm_type,
        use_fake_hardware, right_can_interface, left_can_interface,
    )
    controllers_file_str = context.perform_substitution(controllers_file)
    robot_description_param = {"robot_description": robot_description}

    return [
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            name="robot_state_publisher",
            output="screen",
            parameters=[robot_description_param],
        ),
        Node(
            package="controller_manager",
            executable="ros2_control_node",
            output="both",
            parameters=[robot_description_param, controllers_file_str],
        ),
    ]


def _arm_controller_spawner(context: LaunchContext, robot_controller):
    """robot_controller 값에 따라 양팔 controller spawner 띄움.

    upstream controller_spawner 와 동일 매핑:
      forward_position_controller     → left/right_forward_position_controller
      joint_trajectory_controller     → left/right_joint_trajectory_controller
    """
    rc = context.perform_substitution(robot_controller)
    if rc == "forward_position_controller":
        left, right = "left_forward_position_controller", "right_forward_position_controller"
    elif rc == "joint_trajectory_controller":
        left, right = "left_joint_trajectory_controller", "right_joint_trajectory_controller"
    else:
        raise ValueError(f"Unknown robot_controller: {rc}")

    return [Node(
        package="controller_manager",
        executable="spawner",
        arguments=[left, right, "-c", CONTROLLER_MANAGER_REF],
    )]


def _joint_state_broadcaster(_context: LaunchContext):
    return [Node(
        package="controller_manager",
        executable="spawner",
        arguments=["joint_state_broadcaster", "--controller-manager", CONTROLLER_MANAGER_REF],
    )]


def _gripper_controllers(_context: LaunchContext):
    return [Node(
        package="controller_manager",
        executable="spawner",
        arguments=[
            "left_gripper_controller", "right_gripper_controller",
            "-c", CONTROLLER_MANAGER_REF,
        ],
    )]


def _inactive_forward_position(_context: LaunchContext):
    """live teleop 용 forward_position_controller 두 개를 INACTIVE 로 미리 로드.

    switch_controller 가 활성화하려면 컨트롤러가 'inactive' 상태에 있어야 함 — spawner
    --inactive 플래그로 로드 + configure 만 하고 활성화는 skip.
    """
    return [Node(
        package="controller_manager",
        executable="spawner",
        arguments=[
            "left_forward_position_controller",
            "right_forward_position_controller",
            "--inactive",
            "-c", CONTROLLER_MANAGER_REF,
        ],
    )]


def _soft_start(_context: LaunchContext):
    """controller 활성화 직후 hold-pose 보간 goal — 시작 jerk 완화."""
    return [Node(
        package="eduarm",
        executable="soft_start_node",
        name="eduping_soft_start",
        output="screen",
        parameters=[{"ramp_s": 2.0, "timeout_s": 10.0}],
    )]


def generate_launch_description():
    # 우리 wrapper 가 device-eduping.sh 에서 hardware_type 인자를 전달하는데,
    # upstream 은 use_fake_hardware (bool) 를 받음. 변환 매핑:
    #   hardware_type=mock → use_fake_hardware=true
    #   hardware_type=real → use_fake_hardware=false
    # 별도 hardware_type 인자도 받아주되 내부에서 use_fake_hardware 로 변환.
    declared_arguments = [
        DeclareLaunchArgument("description_package", default_value="openarm_description"),
        DeclareLaunchArgument("description_file", default_value="v10.urdf.xacro"),
        DeclareLaunchArgument("arm_type", default_value="v10"),
        DeclareLaunchArgument("hardware_type", default_value="real",
                              description="real | mock — mock 은 use_fake_hardware=true 로 변환."),
        DeclareLaunchArgument("robot_controller",
                              default_value="joint_trajectory_controller",
                              choices=["forward_position_controller", "joint_trajectory_controller"]),
        DeclareLaunchArgument("runtime_config_package", default_value="openarm_bringup"),
        DeclareLaunchArgument("right_can_interface", default_value="can0"),
        DeclareLaunchArgument("left_can_interface", default_value="can1"),
        DeclareLaunchArgument("controllers_file",
                              default_value="openarm_v10_bimanual_controllers.yaml"),
    ]

    description_package = LaunchConfiguration("description_package")
    description_file = LaunchConfiguration("description_file")
    arm_type = LaunchConfiguration("arm_type")
    hardware_type = LaunchConfiguration("hardware_type")
    robot_controller = LaunchConfiguration("robot_controller")
    runtime_config_package = LaunchConfiguration("runtime_config_package")
    controllers_file = LaunchConfiguration("controllers_file")
    right_can_interface = LaunchConfiguration("right_can_interface")
    left_can_interface = LaunchConfiguration("left_can_interface")

    controllers_file_path = PathJoinSubstitution([
        FindPackageShare(runtime_config_package), "config",
        "v10_controllers", controllers_file,
    ])

    # hardware_type → use_fake_hardware 변환 (Substitution 안에서 직접 비교 어려워
    # OpaqueFunction 으로 처리).
    def _to_use_fake_hardware(context: LaunchContext):
        ht = context.perform_substitution(hardware_type)
        # 'use_fake_hardware' 를 후속 OpaqueFunction 에서 substitution 받게 만들기 위해
        # 별도 LaunchConfiguration 없이 그냥 캡처 변수로 push.
        context.launch_configurations["use_fake_hardware"] = (
            "true" if ht == "mock" else "false"
        )
        return []

    use_fake_hardware = LaunchConfiguration("use_fake_hardware", default="false")

    robot_nodes_spawner_func = OpaqueFunction(
        function=_robot_and_control_nodes,
        args=[description_package, description_file, arm_type, use_fake_hardware,
              controllers_file_path, right_can_interface, left_can_interface],
    )

    delay_s = 1.0
    # soft_start 는 JTC 가 active 가 된 직후에 hold-pose 를 보내야 하므로 spawner
    # 보다 살짝 늦게 (spawn → 활성화 완료까지 ~1s) 띄움.
    soft_start_delay_s = delay_s + 2.0
    return LaunchDescription(
        declared_arguments
        + [OpaqueFunction(function=_to_use_fake_hardware)]
        + [
            robot_nodes_spawner_func,
            TimerAction(period=delay_s,
                        actions=[OpaqueFunction(function=_joint_state_broadcaster)]),
            TimerAction(period=delay_s,
                        actions=[OpaqueFunction(function=_arm_controller_spawner,
                                                args=[robot_controller])]),
            TimerAction(period=delay_s,
                        actions=[OpaqueFunction(function=_gripper_controllers)]),
            TimerAction(period=delay_s,
                        actions=[OpaqueFunction(function=_inactive_forward_position)]),
            TimerAction(period=soft_start_delay_s,
                        actions=[OpaqueFunction(function=_soft_start)]),
        ]
    )
