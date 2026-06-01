"""gogoping_bringup setup."""
import os
from glob import glob
from setuptools import setup

package_name = 'gogoping_bringup'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob(os.path.join('launch', '*.launch.py'))),
        # pi.launch 의 laser_filter 노드가 get_package_share_directory()+/config/laser_filter.yaml
        # 로 참조 — config/ 를 설치하지 않으면 그 경로가 install 에 없어 필터 설정 누락.
        (os.path.join('share', package_name, 'config'),
            glob(os.path.join('config', '*.yaml'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pingdergarten',
    maintainer_email='dev@pingdergarten.local',
    description='GogoPing launch 통합 진입점.',
    license='Proprietary',
    entry_points={
        'console_scripts': [
            'sim_status_publisher = gogoping_bringup.sim_status_publisher:main',
            'sim_battery_node = gogoping_bringup.sim_battery_node:main',
            'sim_teleport_node = gogoping_bringup.sim_teleport_node:main',
            'battery_publisher_node = gogoping_bringup.battery_publisher_node:main',
        ],
    },
)
