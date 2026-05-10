from setuptools import find_packages, setup
import os, glob

package_name = 'gogoping_camera_pan'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob.glob(os.path.join('launch', '*launch.*'))),
        ('share/' + package_name + '/config', glob.glob(os.path.join('config', '*.yaml'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Woolim Park',
    maintainer_email='wooliwooli91@gmail.com',
    description='Camera pan servo control via Arduino Uno serial bridge for gogoping (Pinky).',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'servo_bridge=gogoping_camera_pan.servo_bridge:main',
            'pan_scanner=gogoping_camera_pan.pan_scanner:main',
            'coord_trigger=gogoping_camera_pan.coord_trigger:main',
        ],
    },
)
