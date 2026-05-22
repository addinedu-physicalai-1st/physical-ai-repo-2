"""gogoping_perception setup."""
from setuptools import setup

package_name = 'gogoping_perception'

setup(
    name=package_name,
    version='0.0.1',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', ['launch/perception.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pingdergarten',
    maintainer_email='dev@pingdergarten.local',
    description='YOLO + ByteTrack + ReID 분리 노드.',
    license='Proprietary',
    entry_points={
        'console_scripts': [
            'perception_node = gogoping_perception.perception_node:main',
        ],
    },
)
