"""gogoping_modes setup."""
from setuptools import find_packages, setup

package_name = 'gogoping_modes'

setup(
    name=package_name,
    version='0.1.0',
    # find_packages — fsm/, bt/, interfaces/, utils/ 하위 패키지 자동 발견
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='pingdergarten',
    maintainer_email='dev@pingdergarten.local',
    description='GogoPing 로봇 매니저 — FSM + Behavior Tree.',
    license='Proprietary',
    entry_points={
        'console_scripts': [
            # ros2 run gogoping_modes gogoping_modes 로 띄움
            'gogoping_modes = gogoping_modes.main:main',
        ],
    },
)
