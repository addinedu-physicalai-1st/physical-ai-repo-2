"""d435_camera.launch.py — Intel RealSense D435 를 ROS 토픽으로 publish.

ros-jazzy-realsense2-camera 의 rs_launch.py 가 워낙 인자가 많아 매번 직접 부르기
번거롭다. 본 런치는 우리 octomap 파이프라인에 필요한 최소 설정만 노출한다.

핵심 결정:
  - `camera_name:=d435` 로 frame prefix 통일 → realsense2_camera 의 frame 이름이
    `d435_depth_optical_frame` / `d435_color_optical_frame` 이 되고, URDF (openarm_
    description v10.urdf.xacro) 에 박혀있는 동명 프레임과 그대로 매칭. 별도
    static_transform_publisher 가 필요 없음.
  - `publish_tf:=true` — realsense 가 d435_link → d435_depth_optical_frame 등
    내부 chain 을 TF 로 publish. doctor_teleop.launch.py 의 static_tf 가
    openarm_body_link0 → d435_link 부분을 채워 octomap 이 depth point 를
    world frame 으로 변환 가능.
  - `align_depth.enable:=true` — color 정렬 depth 추가 publish
    (`/d435/aligned_depth_to_color/image_raw`). depth_streamer 구독용.
    octomap 은 raw `/d435/depth/color/points` 그대로 사용.
  - `pointcloud.enable:=true` — MoveIt PointCloudOctomapUpdater + octomap_server
    사이드카 둘 다 pointcloud 를 입력으로 받음. `/d435/depth/color/points` 토픽 생성.
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

        # 참고: rs_launch.py 는 ambient launch_configurations 전체를 순회하며 자기 파라미터가
        # 아닌 건 "Parameter X is not supported" 경고를 낸다(무해 — realsense 가 무시). 부모
        # 인자(control_url 등)가 전파돼 경고가 늘지만 카메라 동작엔 영향 없음.
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
                # depth_streamer 가 color 정렬 depth (/d435/aligned_depth_to_color/image_raw)
                # 를 구독. octomap 은 raw /d435/depth/color/points 그대로 사용.
                "align_depth.enable": "true",
                "pointcloud.enable": "true",
                # profile = WxHxFPS (realsense2_camera 의 string convention)
                "depth_module.depth_profile": [depth_width, "x", depth_height, "x", fps],
                "rgb_camera.color_profile": [color_width, "x", color_height, "x", fps],
                # TF — realsense 가 d435_link → d435_*_optical 자체 chain publish.
                # static_tf (doctor_teleop.launch.py) 가 openarm_body_link0 → d435_link 연결.
                "publish_tf": "true",
                "tf_publish_rate": "0.0",
                "serial_no": serial_no,
                # 빠른 octomap 갱신엔 unite_imu_method 등 IMU 옵션 모두 끔.
                "unite_imu_method": "0",
            }.items(),
        ),
    ])
