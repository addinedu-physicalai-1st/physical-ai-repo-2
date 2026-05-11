"""gogoping_navigation setup."""
import os
from glob import glob
from setuptools import setup

package_name = 'gogoping_navigation'

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
        (os.path.join('share', package_name, 'params'),
            glob(os.path.join('params', '*.yaml'))),
        (os.path.join('share', package_name, 'maps'),
            glob(os.path.join('maps', '*'))),
        (os.path.join('share', package_name, 'rviz'),
            glob(os.path.join('rviz', '*.rviz'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pingdergarten',
    maintainer_email='dev@pingdergarten.local',
    description='GogoPing Nav2 wrapper.',
    license='Proprietary',
    entry_points={'console_scripts': []},
)
