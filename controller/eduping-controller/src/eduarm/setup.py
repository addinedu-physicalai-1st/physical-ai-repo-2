"""eduarm setup."""
import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'eduarm'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        # octomap_demo: sensors_3d.yaml (MoveIt OccupancyMapMonitor 설정) + RViz preset.
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'rviz'), glob('rviz/*.rviz')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pingdergarten',
    maintainer_email='dev@pingdergarten.local',
    description='Pingdergarten OpenArm 노드 묶음.',
    license='Proprietary',
    entry_points={
        'console_scripts': [
            'sim_twin_node = eduarm.sim_twin_node:main',
            'fake_leader_node = eduarm.fake_leader_node:main',
            'feetech_leader_node = eduarm.feetech_leader_node:main',
            # 녹화는 FastAPI bridge (service/control-service/control_service/eduping/ros_bridge.py) 가 처리.
            # 재생은 bridge 가 기본 경로지만, CLI 검증 (yaml 파일 한 개를 한 번 재생)
            # 용으로 standalone 노드 한 개 유지.
            'routines_player_node = eduarm.routines_player_node:main',
            # bringup 직후 양팔 JTC 에 hold-pose 보간 goal 을 보내 시작 jerk 완화.
            'soft_start_node = eduarm.soft_start_node:main',
            # Phase 4 — PointStamped target → TwistStamped (servo_node 입력).
            'servo_reach_node = eduarm.servo_reach_node:main',
            # D435 → control-service WS 스트리머 (ROS 구독 노드). eduping_d435_base.launch.py 가 호출.
            'd435_depth_streamer = eduarm.d435_depth_streamer:main',
            # 하이파이브 hand_point → IK → JointTrajectory. highfive_sim.launch.py 가 호출.
            'highfive_node = eduarm.highfive_node:main',
            # 1Hz 로 /clear_octomap 서비스를 호출 — PointCloudOctomapUpdater stale voxel 제거.
            'clear_octomap_timer = eduarm.clear_octomap_timer:main',
            # 시뮬 부팅 시 양팔을 zero-pose (자연 singularity) → home pose 로 이동.
            'home_pose_setter = eduarm.home_pose_setter:main',
            # Leader → Follower 직결 passthrough — IK 없이 joint 1:1 매핑.
            'leader_passthrough_node = eduarm.leader_passthrough_node:main',
            # Leader joint_states → control-service WS (doctor 머신, cross-machine).
            'leader_ws_uploader_node = eduarm.leader_ws_uploader_node:main',
            # 양방향 teleop WS 브리지 (woobuntu) — leader 수신 + follower /joint_states 송신.
            'teleop_ws_robot_node = eduarm.teleop_ws_robot_node:main',
            # D435 RGB → control-service WebSocket producer (cross-machine ready).
            'd435_rgb_uploader_node = eduarm.d435_rgb_uploader_node:main',
            # D435 depth pointcloud → 1m filter + decimate + world transform → control-service WS.
            'd435_pointcloud_uploader_node = eduarm.d435_pointcloud_uploader_node:main',
            # 무궁화 device-local perception — D435 YOLO/ByteTrack + WS producer.
            'mugunghwa_perception_node = eduarm.mugunghwa_perception_node:main',
            # 근접 안전정지 — D435 depth 로 0.6m 이내 감지 → /eduping/proximity_block.
            'proximity_safety_node = eduarm.proximity_safety_node:main',
        ],
    },
)
