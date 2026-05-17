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
        ],
    },
)
