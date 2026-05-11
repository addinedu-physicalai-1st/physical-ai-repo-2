"""ament_python setup — gogoping_camera 패키지.

console_scripts:
  camera_streamer       — cv2 backend (fallback)
  camera_streamer_v4l2  — v4l2 backend (default, 저지연)

사용:
  ros2 run gogoping_camera camera_streamer_v4l2 --robot gogoping
  ros2 launch gogoping_camera camera_stream.launch.py robot:=gogoping
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
        "GogoPing/EduPing/NoriArm USB 웹캠을 MJPEG 으로 캡처해 Control Server "
        "(UDP) 로 송출하는 패키지. v4l2 직접 (default) 또는 cv2 (fallback) 백엔드."
    ),
    license="Proprietary",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            # cv2 backend (opencv-python-headless 필요)
            "camera_streamer = gogoping_camera.streamer:main",
            # v4l2 backend (linuxpy 필요, Linux 전용)
            "camera_streamer_v4l2 = gogoping_camera.streamer_v4l2:main",
        ],
    },
)
