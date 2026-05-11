# server/control/streaming/

UDP 영상 수신 + WebSocket fan-out 게이트웨이. **별도 uvicorn 프로세스 (port 8100)** 로 실행.

관련 SR: SR-CAM-002 / SR-CAM-003 / SR-CAM-005 ([docs/implementation-plan.md §2.7](../../../docs/implementation-plan.md))
프로토콜 명세는 [protocol.py](protocol.py) 의 헤더 상수와 `parse_video_packet`/`encode_*` 함수 참조.

## 데이터 흐름

```
Pi (camera_streamer.py) ─UDP 9013/9023/9033─→ udp_receiver thread (per robot)
                                                   ↓ call_soon_threadsafe
                                              FrameHub.publish(packet)
                                                   ↓ subscriber 0 → drop (server-side filter)
                                                   ↓ N → client.send_queue.put_nowait
                                              ws_router send_loop → ws.send_bytes
Admin UI (websockets.sync.client) ────WS /ws/video-stream──┘
```

## 모듈

| 파일 | 책임 |
|---|---|
| [`config.py`](config.py) | 포트 매핑 (901X / 902X / 903X), `machine_ips.json` 로드, Settings (env `STREAMING_*`) |
| [`protocol.py`](protocol.py) | UDP 영상 28B 헤더 (CRC32 검증), UDP 제어 12B (intent_seq), WS binary 20B, Pydantic JSON |
| [`udp_receiver.py`](udp_receiver.py) | 로봇별 daemon thread — `socket.recvfrom` blocking, parse → `loop.call_soon_threadsafe(hub.publish)` |
| [`frame_hub.py`](frame_hub.py) | asyncio dispatcher — `(robot_id, stream_id)` → 구독 client 리스트, drop-oldest, server-side filter |
| [`client_registry.py`](client_registry.py) | WSClient dataclass + 인덱스 |
| [`robot_controller.py`](robot_controller.py) | 수동 admin STOP/START 송신 (자동 트리거 X), `intent_seq` 단조 증가, 1초 × 3회 재전송 |
| [`auth.py`](auth.py) | WS 핸드셰이크 cookie 검증 (`session` 쿠키 → AccessToken DB lookup), `require_auth=False` 면 dev anonymous 통과 |
| [`admin_router.py`](admin_router.py) | REST `POST /api/streaming/robots/{robot}/{stop\|start}` (SR-CAM-005) |
| [`ws_router.py`](ws_router.py) | `/ws/video-stream` 핸들러 — welcome/hello/subscribe/unsubscribe/ping/pong + binary frame |
| [`app.py`](app.py) | FastAPI 진입점 — startup hook 에서 receivers 시작 + 5초 boot sanity check |

## 설계 원칙 (PLAN 일치)

- **Pi default ON**: `RobotController` 가 자동 START/STOP 트리거 안 함. Pi 는 부팅 후 항상 송출, server 가 subscriber 0 명일 때 frame 을 drop.
- **server-side filter**: `FrameHub.publish` 가 subscriber 0 명이면 즉시 return → CPU 부담 0.
- **드롭 정책**: 큐 maxsize=1, 가득 차면 가장 오래된 frame drop → 느린 client 가 빠른 client 막지 않음.
- **수동 admin 제어만**: `RobotController.manual_start`/`manual_stop` — `add_subscriber`/`remove_subscriber` 같은 자동 트리거 메서드 없음.
- **intent_seq 단조 증가**: UDP 순서 뒤바뀜 / 빠른 토글에도 마지막 의도가 이김.
- **격리**: UDP 수신 thread 는 GIL release recvfrom 이라 asyncio 메인 루프와 간섭 0.
- **단일 WS, 멀티 영상**: client 하나가 여러 `(robot, stream)` subscribe 가능. binary frame 헤더의 `(robot_id, stream_id)` 로 라우팅.

## 환경변수

| env | 기본 | 의미 |
|---|---|---|
| `STREAMING_REQUIRE_AUTH` | `false` (dev) | `true` 면 session cookie 필수 (운영) |
| `STREAMING_STREAMING_PORT` | 8100 | WebSocket TCP 포트 |
| `STREAMING_HEARTBEAT_INTERVAL_S` | 30 | server → client ping 주기 |
| `STREAMING_HEARTBEAT_TIMEOUT_S` | 60 | pong 무응답 close threshold |
| `STREAMING_BOOT_CHECK_DELAY_S` | 5 | 부팅 후 frame 미수신 시 START 송신 지연 |
| `STREAMING_LOG_LEVEL` | INFO | logging level (app.py 만) |

## 테스트

```bash
bash scripts/test.sh   # streaming 섹션 포함 전체
# 또는 streaming 만:
conda run -n jazzy pytest tests/test_streaming_*.py -v
```

신규 테스트 추가 시 [scripts/test.sh](../../../scripts/test.sh) 의 `Streaming 섹션` 에 기록.

## 통합 검증 (실 카메라 사용)

```bash
# 1. server
scripts/run_server.sh   # tmux 'streaming' window — port 8100/TCP 시작

# 2. Pi 측 — gogoping_camera 패키지 launch (실 카메라 직접 송출)
#    Vic Pinky 에서:
#      cd ~/pingdergarten/device/gogoping_ws
#      source /opt/ros/jazzy/setup.zsh && source install/local_setup.zsh
#      ros2 launch gogoping_camera camera_stream.launch.py
#    또는 bringup 한꺼번에:
#      scripts/device-gogoping-pi.sh

# 3. Server 측 frame 수신 확인
curl -sf http://localhost:8100/health | python3 -m json.tool
#    udp_receivers[0].frames_received 가 25/초로 증가
```

Admin UI 의 GogoPing 대시보드 → 실 영상 표시. 첫 frame ≤100ms.

## 변경 시 주의

- **UDP 수신 thread 안에서는 asyncio 호출 금지** — 반드시 `loop.call_soon_threadsafe`.
- **`FrameHub` / `ClientRegistry` 메서드는 asyncio 단일 thread 에서만 호출** — lock 없음.
- **WS auth 강화 시** `require_auth=true` 로 전환 — 단, Admin UI 가 로그인 흐름 추가 필요 (별도 SR).
- **포트 컨벤션** (9_DD_R 포맷: role 0=예약 ws, role 1=Pi→Server 제어, role 2=Server→Pi 제어, role 3=영상 primary, role 4~9=영상 stream 1~6) 변경 시 [config.py](config.py) + Pi 측 [device/gogoping_ws/src/gogoping/gogoping_camera/gogoping_camera/streamer.py](../../../device/gogoping_ws/src/gogoping/gogoping_camera/gogoping_camera/streamer.py) 동시 갱신.
