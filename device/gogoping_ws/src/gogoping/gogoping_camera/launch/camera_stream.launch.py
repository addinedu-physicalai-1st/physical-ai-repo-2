"""gogoping_camera 카메라 UDP 송출 launch.

SR-CAM-001 (docs/implementation-plan.md §2.7).

Launch 인자 (모두 default 값 있음):
  robot           gogoping | eduping | noriarm    (default: gogoping)
  backend         v4l2 | cv2                       (default: v4l2)
  control_server  shared/machine_ips.json hostname (default: env CONTROL_SERVER_NAME or 'tonyno')

사용 예:
  ros2 launch gogoping_camera camera_stream.launch.py
  ros2 launch gogoping_camera camera_stream.launch.py robot:=gogoping backend:=cv2
  CONTROL_SERVER_NAME=leekt ros2 launch gogoping_camera camera_stream.launch.py

bringup 통합:
  gogoping_bringup/launch/pi.launch.py 가 IncludeLaunchDescription 으로 포함.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import (
    EnvironmentVariable,
    LaunchConfiguration,
    PythonExpression,
)
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    robot = LaunchConfiguration("robot")
    backend = LaunchConfiguration("backend")
    control_server = LaunchConfiguration("control_server")

    return LaunchDescription([
        DeclareLaunchArgument(
            "robot",
            default_value="gogoping",
            description="gogoping | eduping | noriarm — 카메라 송출 패킷의 robot_id",
        ),
        DeclareLaunchArgument(
            "backend",
            default_value="v4l2",
            description="v4l2 (default, 저지연 linuxpy) | cv2 (fallback opencv)",
        ),
        DeclareLaunchArgument(
            "control_server",
            default_value=EnvironmentVariable(
                "CONTROL_SERVER_NAME", default_value="tonyno",
            ),
            description="shared/machine_ips.json 의 hostname key (Control Server IP 결정)",
        ),

        Node(
            package="gogoping_camera",
            # backend == v4l2 → camera_streamer_v4l2, 아니면 camera_streamer (cv2)
            executable=PythonExpression([
                '"camera_streamer_v4l2" if "',
                backend,
                '" == "v4l2" else "camera_streamer"',
            ]),
            name="camera_streamer",
            output="screen",
            additional_env={
                "CAMERA_ROBOT": robot,
                "CONTROL_SERVER_NAME": control_server,
            },
        ),
    ])
