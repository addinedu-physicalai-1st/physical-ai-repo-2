# gogoping_camera_pan

웹캠 2축 (pan / tilt) 서보 (MG995 ×2) 제어. Arduino Uno 가 PWM 출력, Pi/노트북의 ROS2 노드가 시리얼로 명령.

## 하드웨어

| 항목 | 값 |
|---|---|
| MCU | Arduino Uno (시리얼 `/dev/arduino-camera` — udev 고정 심볼릭) |
| Pan servo | MG995, 신호 = **D9** |
| Tilt servo | MG995, 신호 = **D10** |
| 전원 | **외부 5–6V / 1A↑** (USB 5V 금지 — MG995 stall ≈1A) |
| GND | Arduino GND 와 외부 전원 GND **반드시 공통** |

> 전원 끊고 결선. MG995 를 Arduino 5V 핀에서 빨면 Uno 리셋 / USB 포트 손상 가능.

각 축 안전 범위 (펌웨어·노드 양쪽에 클램프):

| 축 | min | center | max |
|---|---|---|---|
| pan | 5° | 90° | 175° |
| tilt | 30° | 90° | 150° |

tilt 끝단은 카메라 케이블/무게중심 고려해 좁힘. 실물 보고 [config/params.yaml](config/params.yaml) 에서 조정.

## udev rule (포트 고정)

USB 를 뽑았다 꽂으면 `/dev/ttyACM{0,1,2,...}` 번호가 들쭉날쭉 — `vendor:product:serial`
세 개를 매칭해서 항상 `/dev/arduino-camera` 로 잡히도록 한 번 설정:

```bash
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="2341", ATTRS{idProduct}=="0043", ATTRS{serial}=="12724551266407105810", SYMLINK+="arduino-camera", MODE="0660", GROUP="dialout"' \
  | sudo tee /etc/udev/rules.d/99-arduino-camera.rules
sudo udevadm control --reload && sudo udevadm trigger
ls -l /dev/arduino-camera   # → ttyACM? 로 심볼릭
```

다른 Uno 로 교체하면 `udevadm info -a -n /dev/ttyACM*` 으로 새 `serial` 값을 받아 룰을 갱신.

## 시리얼 프로토콜

115200 baud, 라인 단위:

```
host -> uno : PT:<pan>,<tilt>\n     (정수 deg)
uno  -> host: OK:<pan>,<tilt>\n     (적용된 deg)
```

펌웨어 watchdog: 1000ms 동안 명령 없으면 (90, 90) 으로 복귀. 그래서 `servo_bridge` 노드는 keypress 가 없어도 `state_pub_hz` (기본 20Hz) 로 현재 setpoint 를 계속 재송신한다.

## 노드

- `servo_bridge` — `~/cmd_pan`, `~/cmd_tilt` (Float32 deg) 구독 → clamp + rate_limit → `PT:` 송신, `OK:` 파싱해서 `~/state` (JointState, joints=[`camera_pan_joint`, `camera_tilt_joint`]) publish
- `keyboard_teleop` — 터미널 raw stdin → `cmd_pan` / `cmd_tilt` publish. TTY 필요해서 launch 가 아니라 `ros2 run` 으로 띄움
- `pan_scanner` — 자동 sin sweep. teleop 과 동시에 못 씀 (둘 다 `/cmd_pan` 으로 publish)

## 키맵 (keyboard_teleop)

| 키 | 동작 |
|---|---|
| `a` / `d` | pan -/+ step |
| `w` / `s` | tilt +/- step (w = 위) |
| `space` | center 복귀 |
| `[` / `]` | step 축소 / 확대 (0.5° ~ 45°) |
| `q`, Ctrl-C | 종료 |

## 실행

```bash
# 1) servo_bridge (시리얼 ↔ Arduino)
ros2 launch gogoping_camera_pan camera_pan.launch.py

# 2) 키보드 teleop (별 터미널에서)
ros2 run gogoping_camera_pan keyboard_teleop --ros-args \
  --params-file install/gogoping_camera_pan/share/gogoping_camera_pan/config/params.yaml

# 자동 sweep (teleop 과 동시 사용 X)
ros2 launch gogoping_camera_pan pan_scanner.launch.py
```

## 펌웨어 업로드

[firmware/servo_bridge/servo_bridge.ino](firmware/servo_bridge/servo_bridge.ino) 를 Arduino IDE 에서 Uno 보드 선택 후 업로드.

## 테스트

순수 헬퍼 (`protocol.py` 의 clamp / rate_limit / parse_ack / encode_cmd) 는 ROS 없이 단위테스트. 위치: [tests/test_camera_pan_protocol.py](../../../../../tests/test_camera_pan_protocol.py). 실행은 루트 [scripts/test.sh](../../../../../scripts/test.sh).
