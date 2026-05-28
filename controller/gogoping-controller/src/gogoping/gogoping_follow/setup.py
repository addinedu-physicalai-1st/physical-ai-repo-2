"""gogoping_follow setup."""
from setuptools import setup
from pathlib import Path
from glob import glob

package_name = 'gogoping_follow'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/follow.launch.py']),
        ('share/' + package_name + '/behavior_trees',
            glob('behavior_trees/*.xml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pingdergarten',
    maintainer_email='dev@pingdergarten.local',
    description='GogoPing 교사 추종 노드 — YOLO + ReID + LiDAR clamp 기반 P 컨트롤.',
    license='Proprietary',
    entry_points={
        'console_scripts': [
            'follow_node = gogoping_follow.follow_node:main',
        ],
    },
)
