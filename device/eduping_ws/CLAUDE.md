# device/eduping_ws

OpenArm 양팔 7DOF + gripper 매니퓰레이터 ROS2 워크스페이스 (eduping 노트북에서 실행).
오른팔 = can0, 왼팔 = can1. lerobot openarm_mini (Feetech bimanual leader) 와 짝.
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
- **`src/eduarm/`** — eduping persona 노드 묶음
  - `sim_twin_node` : `/eduping/joint_trajectory` → 합성 `/joint_states` (실물 없을 때 검증)
  - `fake_leader_node` : `/eduping/leader/joint_states` 합성 sin (실물 mini leader 없을 때 검증)
  - `routines_player_node` : YAML 한 개를 `/eduping/joint_trajectory` 로 단발 publish
  - `launch/sim_only.launch.py` : fake_leader + sim_twin

추후 추가:
- `eduarm` 안 — feetech_leader_node (실물 openarm_mini), admittance_node, ee_teleop_node, arduino_bridge_node (TOF/FSR)
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

## 실행 wrapper

| 스크립트 | 용도 | 비고 |
|---|---|---|
| [scripts/device-eduping.sh](../../scripts/device-eduping.sh) | OpenArm 벤더 bringup (mock / real, bimanual) | follower (실물 팔) |
| [scripts/device-eduping-leader.sh](../../scripts/device-eduping-leader.sh) | 실물 mini leader (`feetech_leader_node`) — `/eduping/leader/joint_states` publisher | USB 시리얼 양팔 (`/dev/ttyUSB0` 오른팔, `/dev/ttyUSB1` 왼팔) |

```bash
# mock — CAN/하드웨어 없이 ros2_control 토픽만
scripts/device-eduping.sh

# 실물 — can0=오른팔, can1=왼팔 (기본). 띄우기 전 16 모터 preflight (openarm-can-motor-check).
HARDWARE_TYPE=real scripts/device-eduping.sh
SKIP_MOTOR_CHECK=1 HARDWARE_TYPE=real scripts/device-eduping.sh   # preflight 우회
```

## 테스트 (무하드웨어 sim — `fake_leader_node` + `sim_twin_node`)

`eduarm` 의 `sim_only.launch.py` 가 가짜 leader(50Hz sin) + sim_twin(controller 대역) 을 띄움.
Control Server 의 녹화/재생 파이프라인을 무하드웨어로 한 번에 닫고 검증할 수 있다.

### 터미널 A — sim 노드

```bash
source /opt/ros/jazzy/setup.bash
source device/eduping_ws/install/setup.bash
ros2 launch eduarm sim_only.launch.py
# 옵션 (필요시): rate_hz:=30  amplitude:=1.2  period_s:=3.0
```

### 터미널 B — Control Server

```bash
scripts/run_server.sh
```
control window 에서 `Eduping ROS bridge 활성화됨` 확인. `Ctrl+B → D` detach.

### 터미널 C — Robot UI

```bash
cd ui/robot-ui && npm run dev
```

브라우저 → eduping 로봇 → 모드 셀렉터 → **관리 → 율동 등록** / **등하원 인사 설정**.
three.js 양팔이 sin 모션으로 흔들리면 토픽 → bridge → WS → UI 전 구간 정상.

### CLI 점검 (선택)

```bash
# 토픽 흐르는지
ros2 topic hz /eduping/leader/joint_states

# 단발 재생 (CLI 에서 morning.yaml 한 번 흘려보내기)
ros2 run eduarm routines_player_node \
  --ros-args -p file:=$(pwd)/shared/openarm_greeting/morning.yaml

# 백엔드 health
curl -s http://localhost:8000/api/eduping/health | jq

# greeting / dance 라이브러리 상태
curl -s http://localhost:8000/api/eduping/greeting | jq
curl -s http://localhost:8000/api/eduping/dance | jq

# greeting 재생 (sim 모드)
curl -s -X POST http://localhost:8000/api/eduping/greeting/morning/play \
  -H 'content-type: application/json' -d '{"target":"sim","speed":1.0}' | jq

# 녹화 사이클 (fake leader → morning 슬롯 덮어쓰기)
curl -s -X POST http://localhost:8000/api/eduping/greeting/morning/record/start | jq
sleep 3
curl -s -X POST http://localhost:8000/api/eduping/greeting/morning/record/stop \
  -H 'content-type: application/json' -d '{"save":true}' | jq
```

## 실물 mini leader 사용

토픽 contract 가 같으므로 publisher 만 교체 — bridge / WS / UI 코드 0 줄 수정.

**인터랙티브 메뉴** (인자 없이 실행) — 또는 인자 `1/2/3` 으로 단계 직지정.

leader (실물 mini leader, USB):
```bash
scripts/device-eduping-leader.sh        # 메뉴: 1) check  2) calibrate  3) bringup
scripts/device-eduping-leader.sh 1      # 모터 점검만
scripts/device-eduping-leader.sh 3      # bringup (= 1 → 2 → tmux 세션)
scripts/device-eduping-leader.sh down
```

follower (실물 OpenArm, CAN):
```bash
scripts/device-eduping.sh               # 메뉴: 1) mock  2) check  3) real
scripts/device-eduping.sh 1             # mock bringup
scripts/device-eduping.sh 3             # real bringup (모터 preflight 후)
scripts/device-eduping.sh down
```

env override:
```bash
SKIP_CHECK=1 scripts/device-eduping-leader.sh 3            # 모터 점검 우회
SKIP_MOTOR_CHECK=1 scripts/device-eduping.sh 3             # follower 측 우회
CALIBRATION_PATH=/path/to.json scripts/device-eduping-leader.sh
PORT_RIGHT=/dev/ttyACM0 PORT_LEFT=/dev/ttyACM1 scripts/device-eduping-leader.sh
RIGHT_CAN=can2 LEFT_CAN=can3 scripts/device-eduping.sh 3
```

leader 의 단계별:
- **1. check** — `feetech_leader_node check_only:=true` 로 양팔 16 모터 ping. 표 형식 ✓/✗ 출력.
- **2. calibrate** — JSON 존재 확인만. 없으면 lerobot calibrate 명령 안내 후 중단 (1 회 셋업).
- **3. bringup** — tmux 세션 `eduping-leader` 안에서 leader 노드 publish.

> ⚠ leader 스크립트는 **conda env `pdg`** 활성 상태에서 실행해야 합니다 (`feetech-servo-sdk` 가
> pdg 에만 설치). 미활성이면 require_env 가 명확한 에러로 중단. `ros2 run` 대신 `python -m
> eduarm.feetech_leader_node` 로 호출해서 시스템 python (`/usr/bin/python3`, scservo_sdk
> 없음) 대신 현재 활성 python 을 사용.

기본 포트는 udev 심볼릭 `/dev/op_mini_right` + `/dev/op_mini_left` (꽂는 순서 무관 고정).
심볼릭 미설정 시 `ttyACM*` 또는 `ttyUSB*` 직접 지정:
```bash
PORT_RIGHT=/dev/ttyACM0 PORT_LEFT=/dev/ttyACM1 scripts/device-eduping-leader.sh
```

udev rule 예 (참고 — 이미 본 머신에 설정됨):
```
# /etc/udev/rules.d/99-openarm-mini.rules — 시리얼 번호 기준으로 좌우 고정
SUBSYSTEM=="tty", ATTRS{idVendor}=="XXXX", ATTRS{serial}=="<right-serial>", SYMLINK+="op_mini_right"
SUBSYSTEM=="tty", ATTRS{idVendor}=="XXXX", ATTRS{serial}=="<left-serial>",  SYMLINK+="op_mini_left"
```

### Calibration

`feetech_leader_node` 가 lerobot 기본 경로의 calibration JSON 을 그대로 읽음:
```
~/.cache/huggingface/lerobot/calibration/teleoperators/openarm_mini/my_mini_leader_arm.json
```
형식 (16 모터 평탄 매핑):
```json
{ "right_joint_1": {"id": 1, "drive_mode": 0, "homing_offset": -1543, "range_min": 0, "range_max": 4095}, ... }
```
없거나 다른 위치면 `CALIBRATION_PATH=/path/to.json scripts/device-eduping-leader.sh`.

신규 leader 셋업 시 한 번은 lerobot 의 calibration GUI 를 돌려서 JSON 을 만들어두는
편이 깔끔 (`python -m lerobot.scripts.lerobot_calibrate` 등 — 본 레포에는 lerobot
미설치, 별도 환경에서 수행).

### 변환 파이프라인 (lerobot openarm_mini.get_action 동일)

1. `sync_read Present_Position` (uint16, 0..4095)
2. normalize → degrees
   - joint: `(raw - mid) * 360 / 4095` (mid = (rmin + rmax) / 2)
   - gripper: `(raw - rmin) / (rmax - rmin) * 100 * (-0.65)`
3. 부호 반전 — `RIGHT_MOTORS_TO_FLIP`/`LEFT_MOTORS_TO_FLIP` 멤버에 한해
4. `JOINT_REMAP` — `joint_6 ↔ joint_7` 좌우 모두
5. degrees → radians → JointState publish


## ROS_DOMAIN_ID

호출 셸의 `ROS_DOMAIN_ID` 를 그대로 사용 (export 안 함). 팀 충돌 방지를 위해 [CLAUDE.md](../../CLAUDE.md) 의 할당 범위 (201~219) 안에서 본인 ID 사용.
