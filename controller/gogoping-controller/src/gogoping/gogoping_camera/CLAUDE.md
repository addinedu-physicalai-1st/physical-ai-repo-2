# gogoping_camera

GogoPing 노트북의 **Intel RealSense D435** 영상을 **WebRTC (H.264 NVENC)** 로 두 경로에 송출하는 ROS2 ament_python 패키지.

영상은 한 번 캡처되어 in-process fan-out:
- **WebRTC**: aiortc MediaRelay → robot-web (LAN P2P) + control-service relay → admin-ui
- **POSIX shm**: gogoping_perception 이 raw frame 으로 직접 읽음 (depth fusion 포함)

관련 SR: SR-CAM-001 (USB MJPEG → D435 + WebRTC 로 갱신).
서버 측: [service/control-service/control_service/streaming/](../../../../../service/control-service/control_service/streaming/) `webrtc_router.py`.

## 모듈

| 파일 | 역할 |
|---|---|
| `gogoping_camera/config.py` | 해상도/fps/bitrate/preset 상수 |
| `gogoping_camera/shm_layout.py` | POSIX shm 이름/크기/dtype (writer+reader 공유) |
| `gogoping_camera/d435_capture.py` | D435 pipeline + rs.align + shm writer |
| `gogoping_camera/webrtc_track.py` | aiortc VideoStreamTrack + NVENC codec opts |
| `gogoping_camera/signaling_client.py` | WS signaling producer 측 |
| `gogoping_camera/webrtc_node.py` | ROS node — capture + WebRTC + signaling lifecycle |

## 해상도 / 코덱

- Color: 1920×1080 @ 30fps (사용자 시청)
- Depth: 848×480 @ 30fps (IR sensor native sweet spot)
- rs.align(color) 로 depth → color 시점 + 1920×1080 으로 upscale
- 640×480 다운스케일 후 shm 에 write (perception 용)
- WebRTC: H.264 NVENC, 4 Mbps, GOP 30, preset p4, tune ll, rc cbr, bf 0

## 사용

```bash
ros2 launch gogoping_camera camera_stream.launch.py
```

`device-gogoping-laptop.sh` 의 camera tmux window 가 자동 launch.

## 의존성

- `librealsense2-utils`, `librealsense2-dev` (apt)
- `ffmpeg` with nvenc support (Ubuntu 24.04 기본)
- `pyrealsense2`, `aiortc`, `av` (Python)
- NVIDIA driver + CUDA (NVENC 용)

[../../../../../CLAUDE.md](../../../../../CLAUDE.md) 의 Python 환경 섹션 참조.

## 검증

```bash
# 1. D435 firmware + USB
rs-enumerate-devices --compact
# 2. NVENC 가용
ffmpeg -encoders 2>/dev/null | grep h264_nvenc
# 3. shm 정리 (비정상 종료 후)
rm -f /dev/shm/gogoping_color_640 /dev/shm/gogoping_depth_640 /dev/shm/gogoping_meta
```

## 폐기

- `streamer.py` / `streamer_v4l2.py`: USB MJPEG → UDP 9013 송출. WebRTC 로 대체됨.
- UDP 와이어 프로토콜 (28B 헤더): gogoping 만 미사용. eduping/noriarm 은 streaming(8100) 에서 유지.
