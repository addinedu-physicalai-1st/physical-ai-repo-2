from setuptools import find_packages, setup

package_name = "noriarm_framework"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    package_data={
        # game.yaml 과 trajectory JSON 을 패키지 안에 함께 배포 — runtime 에서 importlib.resources
        # 로 접근 가능.
        f"{package_name}.games.ox_quiz": ["*.yaml", "*.json"],
        f"{package_name}.games.block_stacking": ["*.yaml", "*.json"],
    },
    include_package_data=True,
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
    ],
    install_requires=["setuptools", "pyyaml"],
    zip_safe=True,
    maintainer="Pingdergarten",
    maintainer_email="wooliwooli91@gmail.com",
    description="NoriArm 게임 프레임워크 — 매니페스트 기반 동적 구성 + 정책 인터페이스",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "noriarm = noriarm_framework.cli:main",
        ],
    },
)
