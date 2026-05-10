from setuptools import setup
from glob import glob

package_name = 'gogoping_navigation'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/map', glob('map/*')),
        ('share/' + package_name + '/rviz', glob('rviz/*.rviz')),
    ],
    install_requires=['setuptools', 'PyYAML'],
    zip_safe=True,
    maintainer='Pingdergarten',
    maintainer_email='dlrkdxor0821@gmail.com',
    description='GogoPing navigation: Nav2 launch + nav graph + map',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={'console_scripts': []},
)
