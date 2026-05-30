from setuptools import find_packages, setup
import os, glob

package_name = 'eduping_stethoscope'

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
    description='FSR402 stethoscope raw reading via Arduino serial bridge for EduPing (OpenArm).',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'fsr_bridge_node=eduping_stethoscope.fsr_bridge_node:main',
            'fsr_ws_uploader_node=eduping_stethoscope.fsr_ws_uploader_node:main',
        ],
    },
)
