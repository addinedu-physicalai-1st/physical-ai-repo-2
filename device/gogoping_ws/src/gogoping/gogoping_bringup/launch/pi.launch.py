"""GogoPing 라즈베리파이용 bringup launch.

vic_pinky_namespaced/launch/gogoping_bringup.launch.py 를 흡수.
upstream submodule 코드는 수정하지 않는다 (AC #19).
sllidar driver 의 frame_id 를 URDF 의 laser_link 와 맞추기 위해
bringup.launch.xml 을 통째 include 하지 않고 동등한 노드 구성을 여기서 기술한다.
"""

from launch import LaunchDescription
from launch.actions import GroupAction, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch_ros.actions import Node, PushRosNamespace
from ament_index_python.packages import get_package_share_directory


def generate_launch_description() -> LaunchDescription:
    pkg_description = get_package_share_directory("vicpinky_description")
    pkg_bringup = get_package_share_directory("vicpinky_bringup")
    pkg_sllidar = get_package_share_directory("sllidar_ros2")
    pkg_camera = get_package_share_directory("gogoping_camera")

    upload = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(pkg_description + "/launch/upload.launch.xml"),
        launch_arguments={"use_sim_time": "False"}.items(),
    )

    # sllidar 의 scan frame_id 를 URDF 의 laser_link 와 일치시킨다
    sllidar = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(pkg_sllidar + "/launch/sllidar_c1_launch.py"),
        launch_arguments={"frame_id": "laser_link"}.items(),
    )

    bringup_node = Node(
        package="vicpinky_bringup",
        executable="bringup",
        parameters=[{
            "accel_limit": 0.4,
            "decel_limit": 1.0,
            "ang_accel_limit": 1.0,
            "ang_decel_limit": 1.5,
        }],
    )

    laser_filter = Node(
        package="laser_filters",
        executable="scan_to_scan_filter_chain",
        parameters=[pkg_bringup + "/config/laser_filter.yaml"],
    )

    # 카메라 UDP MJPEG 송출 (SR-CAM-001) — Pi → Control Server.
    # robot=gogoping 고정. backend / control_server 는 default 또는 호출 셸 env 상속.
    camera_stream = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(
            pkg_camera + "/launch/camera_stream.launch.py"),
        launch_arguments={"robot": "gogoping"}.items(),
    )

    return LaunchDescription([
        GroupAction([
            PushRosNamespace("gogoping"),
            upload,
            sllidar,
            bringup_node,
            laser_filter,
            camera_stream,
        ]),
    ])
