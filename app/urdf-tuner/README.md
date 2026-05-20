# urdf-tuner

Vic Pinky URDF dimension (바퀴 + LIDAR mount/laser) 을 GUI 슬라이더로 편집하는 PyQt5 데스크탑 앱.

값은 단일 YAML — `controller/gogoping-controller/src/vic_pinky/vicpinky_description/config/robot_dims.yaml` — 에 저장된다. 두 곳이 이 파일을 read:

1. `robot_core.xacro` — launch 시 `xacro.load_yaml(...)` 로 URDF property 주입 (RViz / TF / collision).
2. `vicpinky_bringup/bringup.py` — 노드 import 시 `WHEEL_RAD` / `WHEEL_BASE` 로 read (실제 주행 odom / cmd_vel 변환).

→ **single source of truth**. wheel.radius / separation 을 GUI 에서 바꾸면 URDF 와 odom 둘 다 같은 값을 본다.

## 실행

```bash
pip install -e .                # 한 번 (PyQt5 / pyyaml)
python app/urdf-tuner/main.py
```

RViz preview 를 쓸 거면 GUI 실행 전에 ROS 환경 source:

```bash
source /opt/ros/jazzy/setup.bash
source controller/gogoping-controller/install/setup.bash
python app/urdf-tuner/main.py
```

## DEFAULTS

| Section | Key | Default |
|---|---|---|
| wheel | radius | 0.0825 m |
| wheel | thickness | 0.05 m |
| wheel | separation | 0.4288 m |
| wheel | x_offset | 0.0 m (앞/뒤) |
| wheel | z_offset | -0.0048 m (위/아래) |
| lidar | mount_x / y / z | 0.185 / 0.0 / 0.12 m |
| lidar | mount_roll / pitch / yaw | 0 / 0 / 0 rad |
| lidar | laser_x / y / z | 0.0 / 0.0 / 0.03 m |
| lidar | laser_roll / pitch / yaw | 0 / 0 / π rad |

이 값은 `app/urdf-tuner/main.py` 의 `DEFAULTS` dict 와 `robot_dims.yaml` 둘 다에 동시 존재 — 두 곳을 같이 갱신해야 single source of truth 유지.

## 섹션

### 🛞 Wheel / 📡 LIDAR mount / 📡 LIDAR laser
SpinBox 로 직접 입력.

### 🧪 Calibration helpers — 실측값 → 자동 보정

직접 dim 값을 알 필요 없이 실측 결과만으로 보정.

**Wheel radius (직진 테스트)**
1. `cmd_vel` 로 1 m 직진 명령 → 실제 거리를 줄자로 측정.
2. Commanded / Measured 입력 → 미리보기 라벨에서 `radius` 의 before/after 확인.
3. `Apply to wheel.radius` 클릭 → 슬라이더 갱신 (저장 안 됨 상태).
4. 💾 Save → YAML 반영.

식: `new_radius = current_radius × (measured / commanded)`

**Wheel separation (회전 테스트)**
1. 제자리 360° 회전 명령 → 실제 회전각을 측정 (마커, IMU, 또는 시야 기준).
2. Commanded / Measured 입력 → 미리보기.
3. `Apply to wheel.separation` 클릭.
4. 💾 Save.

식: `new_separation = current_separation × (commanded / measured)`
(같은 wheel 회전에서 실측 각도가 작다면 → 실제 wheel base 는 더 큼.)

### 🖥️ RViz live preview

`🚀 Start RViz` 클릭 → 백그라운드에서 `ros2 launch vicpinky_description display.launch.xml` 실행 → `robot_state_publisher` + `joint_state_publisher_gui` + `rviz2` 띄움.

`Save 시 자동 재시작` (기본 ON):
- 💾 Save 또는 Reset to Default 누르면 launch 를 SIGINT → 재시작.
- RViz 가 1~2 초 닫혔다 다시 열리며 새 URDF 가 즉시 반영.

체크박스를 끄면 수동 — 변경 후 직접 `🛑 Stop` → `🚀 Start`.

요구사항: GUI 실행 셸에 ROS 환경 source 되어 있고 워크스페이스가 빌드되어 있어야 함 (`install/setup.bash` 존재). 미충족 시 친절한 에러 다이얼로그.

## 버튼 (하단)

- **💾 Save** — 슬라이더 → YAML dump + (옵션) RViz 재시작.
- **Reset to Default** — 확인 다이얼로그 후 슬라이더 + YAML + (옵션) RViz 모두 `DEFAULTS` 로.
- **Reload from YAML** — 외부 수정 (텍스트 에디터, 다른 팀원의 git pull 등) 다시 read.

## git 동기 흐름

YAML 한 파일이라 머지 충돌 면적이 작다.

1. 작업 전 `git pull` → `Reload from YAML` 로 GUI 동기화.
2. 값 조정 → `Save`.
3. `git diff .../config/robot_dims.yaml` 로 변경 확인.
4. commit / push.

⚠️ wheel.radius / separation 변경 후 실 로봇 적용 시:
```bash
cd controller/gogoping-controller
colcon build --packages-select vicpinky_description vicpinky_bringup --symlink-install
# bringup 노드 재시작
```

## 검증

```bash
python -m py_compile app/urdf-tuner/main.py

cd controller/gogoping-controller
colcon build --packages-select vicpinky_description vicpinky_bringup --symlink-install
source install/setup.bash

# URDF 측 LIDAR origin 확인
xacro install/vicpinky_description/share/vicpinky_description/urdf/robot.urdf.xacro \
    2>&1 | grep -A 1 "lidar_mount_fixed\|laser_link_fixed"

# bringup 측 odom 상수 확인
python3 -c "
import os, sys
sys.path.insert(0, 'install/vicpinky_bringup/lib/python3.12/site-packages')
os.environ['AMENT_PREFIX_PATH'] = os.path.abspath('install/vicpinky_description')
from vicpinky_bringup import bringup
print('WHEEL_RAD =', bringup.WHEEL_RAD)
print('WHEEL_BASE =', bringup.WHEEL_BASE)
"
```
