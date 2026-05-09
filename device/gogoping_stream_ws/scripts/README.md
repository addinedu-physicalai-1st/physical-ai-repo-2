# gogoping_stream_ws/scripts

Pi 측 (Vic Pinky / EduPing 노트북 / NoriArm 노트북) 에서 실행되는 카메라 UDP 송출 스크립트.

설계: [../PLAN.md](../PLAN.md). SR: SR-CAM-001 ([../../../docs/implementation-plan.md](../../../docs/implementation-plan.md) §2.7).

## 파일

| 파일 | 역할 |
|---|---|
| [run_camera.sh](run_camera.sh) | **메인 wrapper** — `CAMERA_BACKEND` env (기본 v4l2) 로 backend 선택 |
| [run_camera_v4l2.sh](run_camera_v4l2.sh) | 명시적 v4l2 alias (저지연) |
| [run_camera_cv2.sh](run_camera_cv2.sh) | 명시적 cv2 alias (fallback) |
| [camera_streamer_v4l2.py](camera_streamer_v4l2.py) | **v4l2 모드 (default)** — linuxpy 로 카메라 native MJPEG 직접 송신 |
| [camera_streamer.py](camera_streamer.py) | **cv2 모드 (fallback)** — opencv 로 캡처+JPEG 재인코딩 |
| README.md | 본 문서 |

## v4l2 (default) vs cv2 (fallback)

| 항목 | **v4l2 (default)** | cv2 (fallback) |
|---|---|---|
| 의존성 | linuxpy (Linux 전용) — `pyproject.toml` 에 포함 | opencv-python-headless |
| 호환성 | Linux 만 (Pi OK) | 모든 환경 |
| 지연 (Pi 측 캡처→송신) | **빠름** (이중 인코드 제거) | 보통 |
| 화질 | 카메라 native MJPEG 그대로 | BGR decode → JPEG re-encode (이중 인코드 손실) |
| frame size 조절 | 카메라 native (v4l2-ctl 필요) | `CAMERA_QUALITY` env 로 자유 조절 |
| 실행 | `run_camera.sh` (default) 또는 `run_camera_v4l2.sh` | `run_camera_cv2.sh` 또는 `CAMERA_BACKEND=cv2 run_camera.sh` |

## 빠른 시작 — Vic Pinky (gogoping)

```bash
# 프로젝트 루트로 이동
cd ~/pingdergarten

# conda 환경 활성화 (또는 venv)
conda activate jazzy

# default (v4l2) — 권장
CAMERA_ROBOT=gogoping device/gogoping_stream_ws/scripts/run_camera.sh

# linuxpy 미설치 / 비-Linux 환경이면 cv2 fallback
CAMERA_ROBOT=gogoping device/gogoping_stream_ws/scripts/run_camera_cv2.sh
```

linuxpy 가 [pyproject.toml](../../../pyproject.toml) 의존성에 포함되어 있어 `pip install -e .` 시 자동 설치 (Linux 한정).

## 동작 요약

- 실행 직후 **default ON** — 즉시 영상 송출 시작 (admin 신호 안 와도)
- Server 의 **수동 STOP** 신호 수신 시에만 일시 중지
- **수동 START** 신호로 재개
- 60초 STOP 유지 시 카메라 핸들 release (전력·USB 부하 ↓)
- SIGINT/SIGTERM 으로 깔끔히 종료

## 빠른 시작

### Vic Pinky (gogoping)

```bash
# 프로젝트 루트로 이동
cd ~/pingdergarten

# conda 환경 활성화 (또는 venv)
conda activate jazzy

# 실행 (server IP 자동 lookup)
CAMERA_ROBOT=gogoping device/gogoping_stream_ws/scripts/run_camera.sh
```

이 명령은 [shared/machine_ips.json](../../../shared/machine_ips.json) 의 `tonyno` 항목 IP 를
Control Server 로 자동 lookup 합니다.

### 환경변수 override

```bash
# 수동 IP 지정 (machine_ips.json 미사용)
CAMERA_ROBOT=gogoping CAMERA_SERVER_IP=192.168.0.99 \
  device/gogoping_stream_ws/scripts/run_camera.sh

# Control Server hostname 변경 — machine_ips.json 의 다른 key 로 lookup
CAMERA_ROBOT=gogoping CONTROL_SERVER_NAME=leekt \
  device/gogoping_stream_ws/scripts/run_camera.sh

# 해상도/fps/품질 변경
CAMERA_ROBOT=gogoping \
  CAMERA_WIDTH=320 CAMERA_HEIGHT=240 CAMERA_FPS=30 CAMERA_QUALITY=60 \
  device/gogoping_stream_ws/scripts/run_camera.sh

# DEBUG 로그
CAMERA_ROBOT=gogoping CAMERA_LOG_LEVEL=DEBUG \
  device/gogoping_stream_ws/scripts/run_camera.sh
```

## 환경변수 / CLI 인자

| env / `--arg` | 기본값 | 설명 |
|---|---|---|
| `CAMERA_ROBOT` / `--robot` | (필수) | `gogoping` / `eduping` / `noriarm` |
| `CAMERA_SERVER_IP` / `--server-ip` | machine_ips.json 의 `tonyno` 자동 lookup | Control Server IP |
| `CAMERA_DEVICE` / `--camera-device` | `/dev/video0` | V4L2 디바이스 |
| `CAMERA_WIDTH` / `--width` | 640 | |
| `CAMERA_HEIGHT` / `--height` | 480 | |
| `CAMERA_FPS` / `--fps` | 25 | |
| `CAMERA_QUALITY` / `--jpeg-quality` | 70 | MJPEG q (1..100) |
| `CAMERA_STREAM_ID` / `--stream-id` | 0 | 0=primary, 1..6=추가 (이번 SR 은 0 만 사용) |
| `CAMERA_LOG_LEVEL` / `--log-level` | INFO | DEBUG/INFO/WARNING/ERROR |

## 포트

9_DD_R 포맷 (DD = robot_id 01~99, R = role 0~9):

| 마지막 자리 (role) | 방향 | 용도 |
|---|---|---|
| 0 | — | 예약 (로봇 장비와 websocket — 추후 SR) |
| 1 | Pi → Server | 제어 (telemetry/error 보고, 추후 SR) |
| 2 | Server → Pi | 제어 (수동 STOP/START + intent_seq) |
| 3 | Pi → Server | 영상 stream 0 (primary) |
| 4 ~ 9 | Pi → Server | 영상 stream 1 ~ 6 (총 7 streams / 로봇) |

| 로봇 | Pi 가 listen (role 2) | Pi 가 send (role 3) | primary 영상 |
|---|---|---|---|
| gogoping | UDP 9012 | → Server UDP 9013 | 9013 |
| eduping | UDP 9022 | → Server UDP 9023 | 9023 |
| noriarm | UDP 9032 | → Server UDP 9033 | 9033 |

## 검증

### 1) Pi 가 송출 중인지 확인 (Pi 호스트에서)

```bash
# 실행 후 다른 터미널에서
ss -lun | grep -E "9012|9013"
# 9012 LISTEN (control listener) 가 보여야 정상
```

### 2) Control Server 가 받고 있는지 확인 (server 호스트에서)

```bash
sudo tcpdump -i any -n udp port 9013 -c 10
# Pi IP → server IP 패킷 ~10개 (각 ~30KB) 확인

# 또는 nc 로 raw 바이트 보기
nc -u -l 9013 | xxd | head
# 첫 4바이트 50 49 4e 47 ("PING") 확인
```

### 3) 수동 STOP/START 테스트 (Server 호스트에서 Pi 로 송신)

```python
# python 한 줄
python3 -c "
import socket, struct
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
# STOP (action=2, intent_seq=1)
s.sendto(struct.pack('!4sBBHI', b'CTRL', 1, 2, 0, 1), ('VIC_PI_IP', 9012))
"
# Pi 로그에 'manual STOP seq=1 from ...' 출력 확인
# tcpdump 에서 9013 frame 끊긴 것 확인
```

START 보낼 때 `action=1` 로 변경, `intent_seq` 는 STOP 보다 큰 값.

## 트러블슈팅

| 증상 | 원인 / 대응 |
|---|---|
| `카메라를 열 수 없습니다: /dev/video0` | `v4l2-ctl --list-devices` 로 디바이스 경로 확인. 권한: `sudo usermod -aG video $USER` |
| `--server-ip 또는 env CAMERA_SERVER_IP 필요` | machine_ips.json 에 `tonyno` 항목 없음 → [scripts/find_machine_ips.sh](../../../scripts/find_machine_ips.sh) 실행 또는 env override |
| `frame XX KB > 65000B — drop` | quality 너무 높음 → `CAMERA_QUALITY=50` 또는 해상도 ↓ |
| Server 측에서 `tcpdump` 에 패킷 보이지 않음 | (1) Pi/Server 같은 LAN? (2) Server IP 맞음? (3) 방화벽 (`sudo ufw allow 9013/udp`) |
| `control listener bind 실패 port 9012` | 다른 프로세스가 점유 — `sudo lsof -i :9012` 으로 확인 |

## 추후 작업 (별도 SR)

| SR | 내용 |
|---|---|
| systemd 등록 | Pi 부팅 시 `camera_streamer.service` 자동 시작 — Q1 (b) 결정에 따라 별도 SR |
| Pi → Server telemetry | port X0 활용, 카메라 에러·CPU·온도 등 보고 |
| 추가 카메라 스트림 (stream_id 1~6) | 후방·그리퍼 카메라 등 |
