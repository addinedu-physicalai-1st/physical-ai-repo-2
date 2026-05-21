"""GogoPing 가제보 시뮬레이션 launch.

gogoping_navigation 의 sim_with_nav2.launch.xml 을 include 한다 — gazebo +
Vic Pinky spawn + nav2 풀스택 (map_server / AMCL / planner / controller /
behavior / bt_navigator / waypoint_follower / costmap) 을 한 번에 띄워
`map → gogoping/odom → gogoping/base_footprint → gogoping/base_link` TF 가
발행되도록 한다.

with_nav2:=false 로 띄우면 기존 launch_sim_with_pinky.launch.xml (nav2 없이
gazebo + spawn 만) 만 띄운다 — nav2 디버깅 / SLAM map 재제작 등에 사용.

map:= / world:= 인자로 PGM·Gazebo world 후보를 절대경로로 swap 가능 —
``~/pingdergarten-maps/cand_XX/{map.yaml,world.sdf}`` 같은 외부 후보 디렉토리를
빌드 없이 바로 테스트.

같은 그룹에 sim_status_publisher 노드를 추가해 /gogoping/sim_active 를 발행,
Control Server 가 sim/real 모드 판정에 사용한다.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from ament_index_python.packages import get_package_share_directory


def generate_launch_description() -> LaunchDescription:
    pkg_nav = get_package_share_directory("gogoping_navigation")
    sim_with_nav2_xml = pkg_nav + "/launch/sim_with_nav2.launch.xml"
    sim_only_xml = pkg_nav + "/launch/launch_sim_with_pinky.launch.xml"

    with_nav2 = LaunchConfiguration("with_nav2")
    map_arg = LaunchConfiguration("map")
    world_arg = LaunchConfiguration("world")
    spawn_x = LaunchConfiguration("spawn_x")
    spawn_y = LaunchConfiguration("spawn_y")
    spawn_z = LaunchConfiguration("spawn_z")
    spawn_yaw = LaunchConfiguration("spawn_yaw")

    pkg_nav_share = FindPackageShare("gogoping_navigation")
    default_map = PathJoinSubstitution([pkg_nav_share, "maps", "map.yaml"])
    default_world = PathJoinSubstitution([pkg_nav_share, "worlds", "pingdergarten.world"])

    return LaunchDescription([
        DeclareLaunchArgument(
            "with_nav2",
            default_value="true",
            description="true → gazebo+spawn+nav2 풀스택, false → gazebo+spawn 만",
        ),
        DeclareLaunchArgument(
            "map",
            default_value=default_map,
            description="map yaml 절대경로 (Nav2 map_server). 후보 swap 시 ~/pingdergarten-maps/cand_XX/map.yaml 형식 전달",
        ),
        DeclareLaunchArgument(
            "world",
            default_value=default_world,
            description="Gazebo world 파일 절대경로 (.world 또는 .sdf). 후보 swap 시 ~/pingdergarten-maps/cand_XX/world.sdf 형식 전달",
        ),
        DeclareLaunchArgument(
            "spawn_x",
            default_value="0.0",
            description="Pinky spawn x (world frame, m).",
        ),
        DeclareLaunchArgument(
            "spawn_y",
            default_value="0.0",
            description="Pinky spawn y (world frame, m).",
        ),
        DeclareLaunchArgument(
            "spawn_z",
            default_value="0.10",
            description="Pinky spawn z (world frame, m).",
        ),
        DeclareLaunchArgument(
            "spawn_yaw",
            default_value="0.0",
            description="Pinky spawn yaw (rad). default = 0.0 (동향, +X)",
        ),
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(sim_with_nav2_xml),
            launch_arguments={
                "namespace": "gogoping",
                "map": map_arg,
                "world": world_arg,
                "spawn_x": spawn_x,
                "spawn_y": spawn_y,
                "spawn_z": spawn_z,
                "spawn_yaw": spawn_yaw,
            }.items(),
            condition=IfCondition(with_nav2),
        ),
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(sim_only_xml),
            launch_arguments={
                "namespace": "gogoping",
                "world": world_arg,
                "spawn_x": spawn_x,
                "spawn_y": spawn_y,
                "spawn_z": spawn_z,
                "spawn_yaw": spawn_yaw,
            }.items(),
            condition=UnlessCondition(with_nav2),
        ),
        Node(
            package="gogoping_bringup",
            executable="sim_status_publisher",
            name="sim_status_publisher",
            namespace="gogoping",
            output="screen",
        ),
    ])
