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

    # sllidar 의 scan frame_id 를 URDF 의 laser_link 와 일치시킨다.
    # serial_port=/dev/rplidar — udev rule (99-vic-pinky.rules) 의 symlink.
    # USB 재할당돼도 항상 같은 path. 기본값 /dev/ttyUSB0 hardcoded 회피.
    sllidar = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(pkg_sllidar + "/launch/sllidar_c1_launch.py"),
        launch_arguments={
            "frame_id": "laser_link",
            "serial_port": "/dev/rplidar",
        }.items(),
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

    # 배터리 publisher — /gogoping/battery 1Hz (sensor_msgs/BatteryState).
    # 상대 토픽 "battery" 사용 → GroupAction 의 PushRosNamespace 가 /gogoping/ prefix.
    # source=voltage_topic: vic_pinky_bringup 이 발행하는 /gogoping/battery_voltage (Float32)
    # 를 구독해서 voltage_min ~ voltage_max 로 0~100% 선형 변환.
    # Vic Pinky: 만충 24V / cutoff 18V (실측). 다른 배터리면 launch arg 로 override.
    battery_publisher = Node(
        package="gogoping_bringup",
        executable="battery_publisher_node",
        parameters=[{
            "source": "voltage_topic",
            "voltage_topic": "battery_voltage",   # 상대 — gogoping namespace 자동 prefix
            "voltage_min": 18.0,
            "voltage_max": 24.0,
            "level": 100.0,                       # voltage 미수신 시 fallback
        }],
    )

    return LaunchDescription([
        GroupAction([
            PushRosNamespace("gogoping"),
            upload,
            sllidar,
            bringup_node,
            laser_filter,
            camera_stream,
            battery_publisher,
        ]),
    ])
