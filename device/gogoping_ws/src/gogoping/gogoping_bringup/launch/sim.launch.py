"""GogoPing 가제보 시뮬레이션 launch.

gogoping_navigation 의 launch_sim_with_pinky.launch.xml 을 namespace='gogoping'
인자로 include 하여 pingdergarten.world + Vic Pinky 가 /gogoping/* 토픽으로
동작하도록 한다. 해당 launch 가 robot_state_publisher / create /
parameter_bridge 의 토픽 이름을 모두 prefix 처리하므로 별도 래핑 불필요.

같은 그룹에 sim_status_publisher 노드를 추가해 /gogoping/sim_active 를 발행,
Control Server 가 sim/real 모드 판정에 사용한다.
"""

from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description() -> LaunchDescription:
    pkg_nav = get_package_share_directory("gogoping_navigation")
    sim_xml = pkg_nav + "/launch/launch_sim_with_pinky.launch.xml"

    return LaunchDescription([
        IncludeLaunchDescription(
            AnyLaunchDescriptionSource(sim_xml),
            launch_arguments={"namespace": "gogoping"}.items(),
        ),
        Node(
            package="gogoping_bringup",
            executable="sim_status_publisher",
            name="sim_status_publisher",
            namespace="gogoping",
            output="screen",
        ),
    ])
