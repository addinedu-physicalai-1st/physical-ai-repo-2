"""ament_python setup — gogoping_camera 패키지.

console_scripts:
  d435_webrtc_node — D435 RGB+Depth 캡처 + WebRTC (aiortc) producer

사용:
  ros2 run gogoping_camera d435_webrtc_node
  ros2 launch gogoping_camera camera_stream.launch.py
"""
from setuptools import find_packages, setup
import os
import glob

package_name = "gogoping_camera"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages",
            ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch",
            glob.glob(os.path.join("launch", "*launch.*"))),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="pingdergarten",
    maintainer_email="dev@pingdergarten.local",
    description=(
        "GogoPing D435 RGB+Depth 캡처 후 WebRTC (aiortc) 로 Control Server 에 송출. "
        "perception 용 다운스케일 frame 은 /dev/shm 에 동시 노출."
    ),
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "d435_webrtc_node = gogoping_camera.webrtc_node:main",
        ],
    },
)
