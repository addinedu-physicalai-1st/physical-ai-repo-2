# gogoping_camera

GogoPing/EduPing/NoriArm 의 USB 웹캠 영상을 MJPEG 으로 캡처해 Control Server (UDP) 로 송출하는 ROS2 ament_python 패키지.

관련 SR: SR-CAM-001 ([docs/implementation-plan.md §2.7](../../../../docs/implementation-plan.md)).
Server 측: [server/control/streaming/](../../../../server/control/streaming/) (port 8100/TCP, `/ws/video-stream`).

## 모듈 구성

| 파일 | 역할 |
|---|---|
| [`gogoping_camera/streamer.py`](gogoping_camera/streamer.py) | **cv2 backend (fallback)** — opencv VideoCapture 로 캡처 + JPEG 재인코딩. `Config`/`StateController` 등 공통 코드 보유 |
| [`gogoping_camera/streamer_v4l2.py`](gogoping_camera/streamer_v4l2.py) | **v4l2 backend (default)** — linuxpy 로 카메라 native MJPEG 직접 송신 (저지연, 이중 인코드 제거) |
| [`launch/camera_stream.launch.py`](launch/camera_stream.launch.py) | ROS2 launch — `robot/backend/control_server` 인자로 backend 선택 |

## 와이어 프로토콜

- UDP 영상 패킷 (28B 헤더 + JPEG): `streamer.py` 의 `VIDEO_HEADER_FMT` 와 `parse_video_packet`
- UDP 제어 패킷 (12B): server 가 STOP/START 송신 (Pi 측 `StateController` 가 listen)
- 포트 매핑: `9_DD_R` (DD=robot_id 01~99, R=role 0~9). `streamer.py` 의 `Config.video_port` / `control_listen_port` 함수 참조

## 사용

### Console scripts (직접 실행)

```bash
# v4l2 backend (default, 저지연)
ros2 run gogoping_camera camera_streamer_v4l2 --robot gogoping
# cv2 fallback
ros2 run gogoping_camera camera_streamer --robot gogoping
```

### Launch (권장)

```bash
# default (gogoping / v4l2 / tonyno)
ros2 launch gogoping_camera camera_stream.launch.py

# 인자 override
ros2 launch gogoping_camera camera_stream.launch.py robot:=eduping backend:=cv2 control_server:=leekt

# 환경변수 override (launch 인자 default 와 연동)
CONTROL_SERVER_NAME=leekt ros2 launch gogoping_camera camera_stream.launch.py
```

### Bringup 통합 (Phase 2 후 자동)

`vic_pinky_namespaced/launch/gogoping_bringup.launch.py` 가 IncludeLaunchDescription 으로 본 launch 를 포함.
`scripts/device-gogoping-pi.sh` 실행 시 bringup 과 함께 자동 시작/종료.

## Launch 인자

| 인자 | 기본값 | 설명 |
|---|---|---|
| `robot` | `gogoping` | UDP 패킷의 `robot_id` 결정 (gogoping/eduping/noriarm) |
| `backend` | `v4l2` | `v4l2` (linuxpy 직접) / `cv2` (opencv fallback) |
| `control_server` | env `CONTROL_SERVER_NAME` 또는 `tonyno` | shared/machine_ips.json 의 hostname key |

추가 환경변수 (직접 실행 시 / Node `additional_env` 로 전달 시):
- `CAMERA_DEVICE` (default `/dev/video0`)
- `CAMERA_WIDTH` / `CAMERA_HEIGHT` / `CAMERA_FPS` / `CAMERA_QUALITY` (cv2 전용)
- `CAMERA_LOG_LEVEL` (DEBUG/INFO/WARNING/ERROR)
- `CAMERA_SERVER_IP` (직접 IP, lookup 우회)

## 의존성

| | |
|---|---|
| build | `ament_python` (setuptools) |
| runtime (v4l2) | `linuxpy>=0.24` (Linux 전용, `pyproject.toml` 에 conditional 등록) |
| runtime (cv2) | `opencv-python-headless` (이미 프로젝트 dep) |

Pi 측 1회 설치:
```bash
cd ~/pingdergarten
pip install -e .   # linuxpy 자동 설치 (Linux)
colcon build --packages-select gogoping_camera --symlink-install
source install/setup.bash
```

## 검증 체크

```bash
# 1. 패키지 빌드
colcon build --packages-select gogoping_camera --symlink-install

# 2. 단독 launch
ros2 launch gogoping_camera camera_stream.launch.py

# 3. Server 측 frame 도착 확인
curl -sf http://<control_server>:8100/health | python3 -m json.tool
# udp_receivers[0].frames_received 가 25/초 속도로 증가
```

## 추후 확장 슬롯 (예약 — 현재 미사용)

| 포트 슬롯 | 용도 | 추후 SR |
|---|---|---|
| `role 0` (X0) | Pi → Server 제어 (telemetry/error 보고) | telemetry SR |
| `role 1` (X1) | Pi → Server 제어 (다른 용도) | TBD |
| `role 4~9` | 추가 영상 stream (후방·그리퍼 카메라 등) | multi-cam SR |

## 변경 시 주의

- 와이어 프로토콜은 server 측 [server/control/streaming/protocol.py](../../../../server/control/streaming/protocol.py) 와 **반드시 일치** 시킬 것 (헤더 포맷, 포트 매핑)
- `parse_known_args()` 사용 — ROS2 launch 가 주입하는 `--ros-args` 를 무시해야 정상 동작
- `streamer_v4l2.py` 는 `streamer.py` 에서 공통 코드 import — `streamer.py` 의 클래스/상수 변경 시 v4l2 도 같이 검증
