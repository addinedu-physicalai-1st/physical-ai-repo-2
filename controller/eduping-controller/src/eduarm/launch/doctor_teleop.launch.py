"""doctor_teleop.launch.py — 원격 진찰 (doctor teleop) arm teleop + MoveIt 부트.

띄움:
  - robot_state_publisher  (양팔 URDF, mock_components 모드)
  - ros2_control_node       (use_fake_hardware:=true → mock_components)
  - controller spawner       joint_state_broadcaster + left/right joint_trajectory_controller
                              + left/right gripper_controller
  - move_group               (MoveIt — planning scene + FK/IK service + collision)

note: 이전엔 moveit_servo × 2 포함했었으나 spec §12 의 hybrid IK 채택 후 무용.
      텔레옵은 leader 가 leader_hybrid_ik_node 를 통해 처리 (leader_teleop.launch.py).

D435/pointcloud/RGB 는 eduping_d435_base.launch.py 가 담당한다.
이 launch 는 arm teleop + MoveIt 스택만 다룬다.
RViz 는 기본 OFF (doctor UI 가 3D 뷰를 담당).

검증 (Task 6 smoke):
  T1) ros2 launch eduarm doctor_teleop.launch.py rviz:=false
  T2) ros2 topic list
       /servo_node/left/status, /servo_node/right/status 보임
       /left_joint_trajectory_controller/joint_trajectory subscriber 있음
       /doctor_teleop/{left,right}/target_pose subscriber 있음 (servo)
  T3) ros2 service call /servo_node_left/start_servo std_srvs/srv/Trigger

설계 메모:
  · 양팔 servo 가 같은 move_group 인스턴스를 listen 하므로 둘 다
    is_primary_planning_scene_monitor=false. move_group 가 primary.
  · hybrid IK (spec §12) 채택 후 moveit_servo / joint_state_relay 제거됨.
    텔레옵 입력은 leader → leader_hybrid_ik_node → JTC.
"""
from __future__ import annotations

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, TimerAction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from moveit_configs_utils import MoveItConfigsBuilder
import xacro


def _build_robot_description() -> str:
    """Render openarm bimanual URDF.

    USE_FAKE_HARDWARE 환경변수:
      "true"  (default) → mock_components (sim)
      "false"           → openarm_hardware (실물 CAN, right=can0 left=can1)
    device-doctor.sh 에서 env 설정 (기본 mock; USE_FAKE_HARDWARE=false 로 실물 override).
    """
    use_fake = os.environ.get("USE_FAKE_HARDWARE", "true")
    description_pkg_share = get_package_share_directory("openarm_description")
    xacro_path = os.path.join(description_pkg_share, "urdf", "robot", "v10.urdf.xacro")
    return xacro.process_file(
        xacro_path,
        mappings={
            "arm_type": "v10",
            "bimanual": "true",
            "use_fake_hardware": use_fake,
            "ros2_control": "true",
            "right_can_interface": "can0",
            "left_can_interface": "can1",
            # 기본 tcp_xyz="0 0 0.08" 은 그리퍼 중심 — 손가락 끝까지 IK 타겟을
            # 늘리기 위해 +Z 로 추가 ~7cm. (finger 길이 + 여유). 의사 핸들의
            # 시각적 위치도 이만큼 앞으로 이동.
            "tcp_xyz": "0 0 0.15",
        },
    ).toprettyxml(indent="  ")




def generate_launch_description() -> LaunchDescription:
    rviz_arg = DeclareLaunchArgument(
        "rviz", default_value="false",
        description="RViz 띄울지 — doctor UI 가 3D 뷰 담당이라 기본 false."
    )

    robot_description = _build_robot_description()
    robot_description_param = {"robot_description": robot_description}

    # ros2_control controllers YAML — openarm_bringup 의 v10 bimanual.
    controllers_file = PathJoinSubstitution([
        FindPackageShare("openarm_bringup"), "config", "v10_controllers",
        "openarm_v10_bimanual_controllers.yaml",
    ])

    # mimic finger_joint2 를 joint_state_broadcaster 에 강제 등록 — 자세한 이유는
    # eduarm/config/jsb_mimic_extras.yaml 헤더 참조.
    jsb_extras_file = PathJoinSubstitution([
        FindPackageShare("eduarm"), "config", "jsb_mimic_extras.yaml",
    ])

    # MoveIt 설정 (move_group + servo 공통 robot_description_semantic / kinematics).
    moveit_config = MoveItConfigsBuilder(
        "openarm", package_name="openarm_bimanual_moveit_config"
    ).to_moveit_configs()
    moveit_params = moveit_config.to_dict()

    bimanual_share = get_package_share_directory("openarm_bimanual_moveit_config")

    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        name="robot_state_publisher",
        output="screen",
        parameters=[robot_description_param],
    )

    ros2_control_node = Node(
        package="controller_manager",
        executable="ros2_control_node",
        output="both",
        parameters=[robot_description_param, controllers_file, jsb_extras_file],
    )

    # --controller-manager-timeout 으로 controller_manager 가 살아날 때까지 spawner 가
    # 대기 — TimerAction 의 race 를 막아준다.
    joint_state_broadcaster_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=[
            "joint_state_broadcaster",
            "--controller-manager-timeout", "30",
            "--controller-manager", "/controller_manager",
        ],
    )

    arm_controller_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=[
            "left_joint_trajectory_controller",
            "right_joint_trajectory_controller",
            "--controller-manager-timeout", "30",
            "-c", "/controller_manager",
        ],
    )

    gripper_controller_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=[
            "left_gripper_controller",
            "right_gripper_controller",
            "--controller-manager-timeout", "30",
            "-c", "/controller_manager",
        ],
    )

    move_group_node = Node(
        package="moveit_ros_move_group",
        executable="move_group",
        name="move_group",
        output="screen",
        parameters=[moveit_params],
    )

    # Controller spawner 는 ros2_control_node 가 뜬 뒤에 등록되어야 함.
    LAUNCH_DELAY_SECONDS = 1.5
    delayed_jsb = TimerAction(
        period=LAUNCH_DELAY_SECONDS, actions=[joint_state_broadcaster_spawner]
    )
    delayed_arm = TimerAction(
        period=LAUNCH_DELAY_SECONDS, actions=[arm_controller_spawner]
    )
    delayed_gripper = TimerAction(
        period=LAUNCH_DELAY_SECONDS, actions=[gripper_controller_spawner]
    )

    # mock_components 의 initial_value 가 모두 0.0 인 자연 singularity 회피용 —
    # controller spawn 직후 양팔을 home pose 로 이동. 실물 HW 에선 사용 금지
    # (현재 자세에서 즉시 home 으로 가버리면 위험) — USE_FAKE_HARDWARE=false 면 skip.
    enable_home_pose = os.environ.get("USE_FAKE_HARDWARE", "true").lower() != "false"
    home_pose_setter = Node(
        package="eduarm",
        executable="home_pose_setter",
        name="eduarm_home_pose_setter",
        output="screen",
    )
    delayed_home = TimerAction(period=LAUNCH_DELAY_SECONDS + 2.0, actions=[home_pose_setter])

    # leader → follower joint 1:1 passthrough — IK 없음, move_group FK/IK 호출 0.
    # UI 의 Telehealth 버튼이 ~/set_active 호출 전엔 idle.
    leader_passthrough = Node(
        package="eduarm",
        executable="leader_passthrough_node",
        name="leader_passthrough",
        output="screen",
    )
    delayed_passthrough = TimerAction(
        period=LAUNCH_DELAY_SECONDS + 4.5, actions=[leader_passthrough]
    )

    # RViz 옵션 — doctor UI 가 메인 뷰지만 ROS 디버깅용으로 켤 수도 있음.
    # RViz 설정은 eduarm 패키지로 관리 (submodule 인 openarm_bimanual_moveit_config 대신).
    # 메인 repo 에 commit 됨 → 팀원/머신 간 공유 가능.
    rviz_config = os.path.join(
        get_package_share_directory("eduarm"), "rviz", "doctor_teleop.rviz"
    )
    rviz_node = Node(
        package="rviz2",
        executable="rviz2",
        name="rviz2",
        output="log",
        arguments=["-d", rviz_config],
        parameters=[moveit_params],
        condition=IfCondition(LaunchConfiguration("rviz")),
    )

    actions = [
        rviz_arg,
        robot_state_publisher,
        ros2_control_node,
        delayed_jsb,
        delayed_arm,
        delayed_gripper,
        move_group_node,
        delayed_passthrough,
        rviz_node,
    ]
    if enable_home_pose:
        actions.insert(actions.index(move_group_node), delayed_home)
    return LaunchDescription(actions)
