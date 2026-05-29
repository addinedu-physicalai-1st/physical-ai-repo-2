# D435 카메라 상시 세트 자동 시작 (Linux + USB hotplug)

EduPing 의 D435 RealSense 카메라를 노트북 USB 에 꽂으면 자동으로 `eduping_d435_base.launch.py`
(realsense2_camera + rgb/pointcloud/depth bridge + static TF) 가 뜨고, 뽑으면 자동으로 멈추도록
udev + systemd 로 설정해뒀습니다. 본인 머신에도 똑같이 깔고 싶으면 ↓

무궁화 perception (YOLO) 은 base 에 포함되지 않습니다. 게임 시작 시
`scripts/device-eduping-d435.sh game` 으로 별도 기동.

## 1회 설치

> 전제 조건: eduarm colcon build 완료 (아래 "전제 조건" 섹션 참조)

```bash
sudo bash scripts/d435-autostart/install.sh
```

[install.sh](install.sh) 가 [d435-streamer.service.template](d435-streamer.service.template) 의 placeholder
(`__USER__` / `__GROUP__` / `__HOME__` / `__REPO_ROOT__`) 를 현재 환경에 맞춰
치환한 뒤 `/etc/systemd/system/d435-streamer.service` 로 설치합니다. 동시에:

- `/etc/udev/rules.d/99-d435-autostart.rules` 설치 (USB hotplug rule)
- `systemctl daemon-reload` + `udevadm trigger` (이미 꽂혀 있어도 즉시 시작)

자동 감지 규칙:

| placeholder | 감지 방식 |
|---|---|
| `__USER__`      | `$SUDO_USER` (sudo 호출자) |
| `__GROUP__`     | `id -gn $SUDO_USER` |
| `__HOME__`      | `getent passwd $SUDO_USER` |
| `__REPO_ROOT__` | `install.sh` 위치 기준 두 단계 상위 |

ExecStart 는 `ros2 launch` (system python3 / C++) 를 사용하므로 conda python 경로 (`__PYTHON__`) 는 더 이상 필요하지 않습니다.

## 확인

```bash
systemctl status d435-streamer.service             # 상태
journalctl -u d435-streamer.service -f             # 라이브 로그
curl -s http://localhost:8100/health | jq .depth   # 서버 frame 수신 (latest_seq 가 계속 증가)
```

USB 뽑았다 다시 꽂아서 자동으로 stop / start 되는지 확인하면 끝.

## 제거

```bash
sudo bash scripts/d435-autostart/uninstall.sh
```

## 전제 조건

- eduarm 패키지 colcon build 완료 (`ros2 launch` 진입점 필요)
  ```bash
  cd controller/eduping-controller
  source /opt/ros/jazzy/setup.bash
  colcon build --packages-select eduarm --symlink-install
  ```
- ROS2 apt 패키지: `ros-jazzy-realsense2-camera`, `ros-jazzy-cv-bridge`, `ros-jazzy-tf2-ros`
  (apt 설치, conda env 불필요)
- control-service 가 8100 에서 떠 있어야 depth frame 이 실제로 흐름 (안 떠 있어도 bridge 자체는 살아있고 reconnect backoff 로 대기)
- `ultralytics` 등 무궁화 게임 전용 패키지는 base 에 불필요 — `scripts/device-eduping-d435.sh game` 시 별도 기동

## 작동 원리

3종 콤보로 plug ↔ unplug 가 깔끔하게 처리됨:

| 메커니즘 | 역할 |
|---|---|
| `ENV{SYSTEMD_WANTS}+=d435-streamer.service` (udev rule) | USB device 가 present 인 동안 service 를 keep-alive |
| `StopWhenUnneeded=yes` (systemd unit) | 아무도 service 를 want 안 하면 (= USB 뽑힘) 자동 stop |
| `Restart=on-failure` (systemd unit) | pyrealsense2 hiccup 시 2초 대기 후 자동 재시작 |

`SYSTEMD_WANTS` 는 USB hotplug 의 표준 systemd 통합 방법 (Intel RealSense, ROS bringup, NetworkManager 등 모두 같은 패턴 사용).

## 트러블슈팅

- **service 가 active 인데 frame 이 안 흐름** — `journalctl -u d435-streamer.service -n 50` 으로 streamer 로그 확인.
  - `frame timeout` 만 반복 → RealSense 가 hung 상태 (pipeline 은 열렸는데 프레임 없음). **USB 뽑았다 꽂기** 후 `systemctl restart d435-streamer.service`.
  - `RealSense error` / `Device or resource busy` → 다른 프로세스가 카메라 점유 중이거나 reset 직후 — realsense2_camera 노드 하나만 띄울 것 (base launch 가 단일 opener를 보장).
  - `WS disconnect` 반복 → `curl -s http://localhost:8100/health` 로 streaming(8100) 가동 확인, `run_server.sh` 재시작.
  - UI `뎁스 끊김` + health `latest_seq` 비어 있음 → producer 가 프레임을 못 보내는 상태 (위와 동일).
- **USB 꽂아도 service 시작 안 됨** — `udevadm monitor --subsystem-match=usb` 로 udev 이벤트가 발생하는지 확인. 발생하지만 service 가 안 뜨면 rule 파일에 오타가 있을 수 있음.
- **여러 D435 동시 연결** — 현재 rule 은 첫 번째 device 에 대해서만 동작. 멀티 device 는 별도 SR.
- **D435 가 아닌 다른 RealSense (D435i / D455)** — [99-d435-autostart.rules](99-d435-autostart.rules) 의 `ATTR{idProduct}` 매칭에 다른 product id 추가:
  - D435: `0b07`
  - D435i: `0b3a`
  - D455: `0b5c`

## 파일 목록

| 파일 | 역할 |
|---|---|
| [d435-streamer.service.template](d435-streamer.service.template) | systemd unit 템플릿 (placeholder 포함, 직접 systemctl 에 먹이지 말 것) |
| [99-d435-autostart.rules](99-d435-autostart.rules) | udev rule (USB hotplug → SYSTEMD_WANTS) |
| [install.sh](install.sh) | 템플릿 렌더링 + /etc/ 설치 + reload + trigger |
| [uninstall.sh](uninstall.sh) | install.sh 의 reverse |
