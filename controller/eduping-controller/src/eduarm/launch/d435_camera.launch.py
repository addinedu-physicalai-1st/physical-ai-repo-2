"""d435_camera.launch.py — Intel RealSense D435 를 ROS 토픽으로 publish.

ros-jazzy-realsense2-camera 의 rs_launch.py 가 워낙 인자가 많아 매번 직접 부르기
번거롭다. 본 런치는 우리 octomap 파이프라인에 필요한 최소 설정만 노출한다.

핵심 결정:
  - `camera_name:=d435` 로 frame prefix 통일 → realsense2_camera 의 frame 이름이
    `d435_depth_optical_frame` / `d435_color_optical_frame` 이 되고, URDF (openarm_
    description v10.urdf.xacro) 에 박혀있는 동명 프레임과 그대로 매칭. 별도
    static_transform_publisher 가 필요 없음.
  - `publish_tf:=false` — TF 는 URDF (robot_state_publisher) 가 이미 송출하므로
    중복 publish 방지. (realsense2_camera 가 부모 link 없이 띄우는 d435_link 가
    URDF tree 의 d435_link 와 충돌하지 않도록.)
  - `align_depth.enable:=false` — octomap 은 depth 본연 intrinsics 그대로 받는 게
    가장 정확. aligned-to-color 는 색감 시각화용일 뿐.
  - `pointcloud.enable:=false` — MoveIt DepthImageOctomapUpdater 는 depth image
    한 장씩 받는 plugin. point_cloud 토픽 따로 만들 필요 없음.
  - default 해상도/fps 는 기존 d435_depth.launch.py (WS 스트리머) 와 동일하게
    424×240 @ 15fps. octomap 갱신 부담 + USB bandwidth 둘 다 가볍게.

사용:
  ros2 launch eduarm d435_camera.launch.py
  ros2 launch eduarm d435_camera.launch.py depth_width:=640 depth_height:=480 fps:=30

체크:
  ros2 topic hz /d435/depth/image_rect_raw    # ~15 Hz
  ros2 topic echo /d435/depth/camera_info --once
"""
from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    fps = LaunchConfiguration("fps")
    depth_width = LaunchConfiguration("depth_width")
    depth_height = LaunchConfiguration("depth_height")
    color_width = LaunchConfiguration("color_width")
    color_height = LaunchConfiguration("color_height")
    serial_no = LaunchConfiguration("serial_no")

    return LaunchDescription([
        DeclareLaunchArgument("fps", default_value="15"),
        DeclareLaunchArgument("depth_width", default_value="424"),
        DeclareLaunchArgument("depth_height", default_value="240"),
        DeclareLaunchArgument("color_width", default_value="424"),
        DeclareLaunchArgument("color_height", default_value="240"),
        DeclareLaunchArgument(
            "serial_no", default_value="''",
            description="여러 RealSense 가 꽂혔을 때 시리얼 (앞에 _ 붙여 string force)."
                        " e.g. _123456789. 기본 빈 string → 첫 장치.",
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                PathJoinSubstitution([
                    FindPackageShare("realsense2_camera"),
                    "launch", "rs_launch.py",
                ]),
            ),
            launch_arguments={
                "camera_name": "d435",
                "camera_namespace": "",
                # depth + color enable, aligned/pointcloud 끔.
                "enable_depth": "true",
                "enable_color": "true",
                "enable_infra1": "false",
                "enable_infra2": "false",
                "enable_gyro": "false",
                "enable_accel": "false",
                "align_depth.enable": "false",
                "pointcloud.enable": "false",
                # profile = WxHxFPS (realsense2_camera 의 string convention)
                "depth_module.depth_profile": [depth_width, "x", depth_height, "x", fps],
                "rgb_camera.color_profile": [color_width, "x", color_height, "x", fps],
                # TF 는 URDF 가 책임.
                "publish_tf": "false",
                "tf_publish_rate": "0.0",
                "serial_no": serial_no,
                # 빠른 octomap 갱신엔 unite_imu_method 등 IMU 옵션 모두 끔.
                "unite_imu_method": "0",
            }.items(),
        ),
    ])
