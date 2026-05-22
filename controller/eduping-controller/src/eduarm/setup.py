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
            # D435 → control-service WS 스트리머. d435_depth.launch.py 가 호출.
            'd435_depth_streamer = eduarm.d435_depth_streamer:main',
            # 하이파이브 hand_point → IK → JointTrajectory. highfive_sim.launch.py 가 호출.
            'highfive_node = eduarm.highfive_node:main',
        ],
    },
)
