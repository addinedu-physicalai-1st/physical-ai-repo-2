"""gogoping_navigation setup — Nav2 wrapper + Gazebo 시뮬레이션 환경."""
import os
from glob import glob
from setuptools import setup

package_name = 'gogoping_navigation'


def _data_glob(subdir, pattern='*'):
    """share/<pkg>/<subdir>/ 로 설치할 파일 목록."""
    return (
        os.path.join('share', package_name, subdir),
        glob(os.path.join(subdir, pattern)),
    )


setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        _data_glob('launch', '*.launch.xml'),
        _data_glob('config', '*.yaml'),
        _data_glob('params', '*.yaml'),
        _data_glob('behavior_trees', '*.xml'),
        _data_glob('maps', '*'),
        _data_glob('rviz', '*.rviz'),
        _data_glob('urdf', '*.xacro'),
        ('share/' + package_name + '/worlds',
            glob('worlds/*.world') + glob('worlds/*.sdf')),
        # models (Gazebo) — 디렉토리 트리 보존
        (os.path.join('share', package_name, 'models', 'pingdergarten'),
            glob(os.path.join('models', 'pingdergarten', '*.sdf')) +
            glob(os.path.join('models', 'pingdergarten', '*.config'))),
        (os.path.join('share', package_name, 'models', 'pingdergarten',
                      'materials', 'textures'),
            glob(os.path.join('models', 'pingdergarten', 'materials',
                              'textures', '*.png'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pingdergarten',
    maintainer_email='dev@pingdergarten.local',
    description='GogoPing Nav2 wrapper + Gazebo 시뮬레이션 환경.',
    license='Proprietary',
    entry_points={
        'console_scripts': [
            'echo_pose = gogoping_navigation.echo_pose:main',
            'graph_router_node = gogoping_navigation.graph_router_node:main',
        ],
    },
)
