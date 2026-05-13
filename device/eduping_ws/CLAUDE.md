# device/eduping_ws

OpenArm 7DOF 매니퓰레이터 ROS2 워크스페이스 (eduping 노트북에서 실행).
용도: 율동(룰베이스) · 등하원 인사(룰베이스) · 원격 진찰(EE teleop + admittance).

## 구성

| 패키지 | 출처 | 용도 |
|---|---|---|
| `openarm_can` | https://github.com/enactic/openarm_can | SocketCAN 저수준 라이브러리 |
| `openarm_description` | https://github.com/enactic/openarm_description | URDF · meshes |
| `openarm_ros2/openarm` | https://github.com/enactic/openarm_ros2 | 메타패키지 |
| `openarm_ros2/openarm_hardware` | ↑ | ros2_control 하드웨어 인터페이스 |
| `openarm_ros2/openarm_bringup` | ↑ | 런치 (`openarm.launch.py`, `openarm.bimanual.launch.py`) |
| `openarm_ros2/openarm_bimanual_moveit_config` | ↑ | MoveIt 설정 (양팔) |
| `openarm_teleop` | https://github.com/enactic/openarm_teleop | 물리 leader-follower (현재 시나리오 미사용, 보존만) |

미포함 / 별도 처리:
- **PEAK CAN 드라이버** — git 저장소가 아닌 tarball 배포. 벤더에서 받아 호스트에 설치 (`peak-linux-driver` apt 또는 소스). submodule 안 함.
- **lerobot** — 진찰 MVP 에 불필요. 나중에 모방학습 추가 시 별도 워크스페이스로.

본 레포 직속 패키지:
- **`src/pingdergarten_openarm/`** — eduping persona 노드 묶음
  - `sim_twin_node` : `/eduping/joint_trajectory` → 합성 `/joint_states` (실물 없을 때 검증)
  - `fake_leader_node` : `/eduping/leader/joint_states` 합성 sin (실물 mini leader 없을 때 검증)
  - `routines_player_node` : YAML 한 개를 `/eduping/joint_trajectory` 로 단발 publish
  - `launch/sim_only.launch.py` : fake_leader + sim_twin

추후 추가:
- `pingdergarten_openarm` 안 — feetech_leader_node (실물 openarm_mini), admittance_node, ee_teleop_node, arduino_bridge_node (TOF/FSR)
- `firmware/openarm_sensors/` — Arduino 스케치

## 빌드

```bash
# eduping 노트북에서
cd device/eduping_ws
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

`rosdep install` 시 PEAK 드라이버 미설치면 `openarm_hardware` 가 실패할 수 있음 — 그 경우 일단 `--packages-skip openarm_hardware` 로 description/bringup 만 빌드해서 mock 모드로 검증.

## 빠른 실행

```bash
# OpenArm 벤더 bringup — 무하드웨어 (CAN 없이 mock 으로 토픽만 띄우기)
scripts/device-eduping.sh

# OpenArm 벤더 bringup — 실물 (CAN 연결 필요)
HARDWARE_TYPE=real CAN_INTERFACE=can0 scripts/device-eduping.sh
```

옵션은 [scripts/device-eduping.sh](../../scripts/device-eduping.sh) 참고.

## sim-only 검증 (벤더 bringup 없이 녹화/재생 파이프라인만)

`pingdergarten_openarm` 의 fake leader + sim twin 만 띄워서 Control Server 의
녹화/재생 흐름을 무하드웨어로 검증할 수 있다.

```bash
source /opt/ros/jazzy/setup.bash
source device/eduping_ws/install/setup.bash
ros2 launch pingdergarten_openarm sim_only.launch.py
```

다른 터미널:

```bash
# 1. fake leader 가 50Hz 로 publish 중인지
ros2 topic hz /eduping/leader/joint_states

# 2. dummy greeting yaml 한 번 재생 → sim_twin 이 /joint_states echo
ros2 run pingdergarten_openarm routines_player_node \
  --ros-args -p file:=$(pwd)/shared/openarm_greeting/morning.yaml

# 3. sim_twin 이 받아서 /joint_states 발행하는지
ros2 topic echo /joint_states --once
```

Control Server (FastAPI) 도 같은 환경에서 띄우면 `/api/eduping/*` 와 WS 가 살아남:

```bash
# 같은 ROS env 가 source 된 셸에서
scripts/run_server.sh   # 또는 본인 환경의 uvicorn 진입점

# 다른 터미널 — health
curl -s http://localhost:8000/api/eduping/health | jq

# greeting 슬롯 상태 (morning 만 dummy 가 있어 채워짐)
curl -s http://localhost:8000/api/eduping/greeting | jq

# greeting 재생 (sim 모드, 1배속)
curl -s -X POST http://localhost:8000/api/eduping/greeting/morning/play \
  -H 'content-type: application/json' -d '{"target":"sim","speed":1.0}' | jq

# WS 테스트 (websocat 또는 wscat)
websocat ws://localhost:8000/api/eduping/state
websocat ws://localhost:8000/api/eduping/recording
```

녹화 검증 (fake leader 의 sin 모션 → greeting 슬롯 덮어쓰기):

```bash
curl -s -X POST http://localhost:8000/api/eduping/greeting/morning/record/start | jq
sleep 3
curl -s -X POST http://localhost:8000/api/eduping/greeting/morning/record/stop \
  -H 'content-type: application/json' -d '{"save":true}' | jq
# → shared/openarm_greeting/morning.yaml 가 새 keyframes 로 덮어쓰기 됨
```

## ROS_DOMAIN_ID

호출 셸의 `ROS_DOMAIN_ID` 를 그대로 사용 (export 안 함). 팀 충돌 방지를 위해 [CLAUDE.md](../../CLAUDE.md) 의 할당 범위 (201~219) 안에서 본인 ID 사용.
