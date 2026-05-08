"""Wrapper launch — vicpinky_bringup 의 bringup.launch.xml 을 'gogoping' namespace 아래로.

upstream submodule 코드는 수정하지 않는다 (AC #19).
변경 가능성이 있는 launch 인자는 BRINGUP_ARGS dict 한 곳에 모은다.
"""

from launch import LaunchDescription
from launch.actions import GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch_ros.actions import PushRosNamespace
from ament_index_python.packages import get_package_share_directory


# 변경 가능성이 높은 launch 인자는 여기서만 수정 (위험 #6 완화)
BRINGUP_ARGS = {
    "use_sim_time": "False",
}


def generate_launch_description() -> LaunchDescription:
    bringup_xml = (
        get_package_share_directory("vicpinky_bringup")
        + "/launch/bringup.launch.xml"
    )

    bringup = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(bringup_xml),
        launch_arguments=list(BRINGUP_ARGS.items()),
    )

    return LaunchDescription([
        GroupAction([
            PushRosNamespace("gogoping"),
            bringup,
        ]),
    ])
