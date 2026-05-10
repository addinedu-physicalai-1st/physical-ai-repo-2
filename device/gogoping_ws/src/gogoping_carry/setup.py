from setuptools import setup
from glob import glob

package_name = 'gogoping_carry'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.py')),
    ],
    install_requires=['setuptools', 'PyYAML'],
    zip_safe=True,
    maintainer='Pingdergarten',
    maintainer_email='dlrkdxor0821@gmail.com',
    description='GogoPing carry: 교사 추종 (camera ReID + LiDAR distance control)',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            # 추후 추가:
            # 'graph_visualizer = gogoping_carry.graph_visualizer:main',
            # 'point_picker     = gogoping_carry.point_picker:main',
            # 'carry_action_server = gogoping_carry.carry_action_server:main',
        ],
    },
)
