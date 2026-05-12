---
confluence_page_id: "40763394"
confluence_url: "https://woolimi.atlassian.net/wiki/spaces/FN/pages/40763394/Folder+Structure"
title: "Folder Structure"
confluence_version: 6
last_synced: "2026-05-06T14:29:29"
---

# 폴더 구조

```
pingdergarten/
├── .env                              # Atlassian 토큰 등 (모든 스크립트의 단일 소스, .gitignore)
├── .env.example
├── docker-compose.yaml               # control / ai / postgres / minio
├── CLAUDE.md
│
├── docs/                             # Confluence 와 양방향 동기화되는 설계 문서
│   ├── user-requirements.md
│   ├── system-requirements.md
│   ├── implementation-plan.md
│   ├── system-architecture.md
│   ├── tech-stack.md
│   ├── folder-structure.md
│   └── robots/
│       ├── openarm.md                # EduPing 듀얼 암
│       ├── vic-pinky.md              # GogoPing 모바일 베이스
│       └── omx-ai.md                 # NoriArm 매니퓰레이터
│
├── .gitmodules                       # vendor 패키지 (vic_pinky, NoriArm open_manipulator) submodule 정의
├── scripts/                          # 평면 구조, 접두어로 분류
│   ├── pull_docs.sh                  # Confluence → docs/ pull
│   ├── push_docs.sh                  # docs/ → Confluence push
│   ├── _sync_docs/                   # 동기화 모듈 (Python)
│   ├── run_server.sh                 # tmux: postgres + pgweb 컨테이너 + AI Hub + Control 통합 실행
│   ├── stop_server.sh                # docker compose down (postgres + pgweb 컨테이너 종료)
│   ├── db-seed.sh                    # alembic upgrade head + 31일치 menu / named pose seed 주입
│   ├── ui-robot.sh                   # 인자로 eduping/gogoping/noriarm 받아 VITE_ROBOT 분기 후 vite dev
│   ├── ui-portal.sh                  # portal-ui vite dev
│   ├── ui-admin.sh                   # python -m admin_app
│   ├── device-gogoping-pi.sh         # GogoPing 라즈베리파이 — vicpinky_bringup (모터·LiDAR)
│   ├── device-gogoping-laptop.sh     # GogoPing 노트북 — Nav2/SLAM + gogoping_* 응용 + 비전
│   ├── device-eduping.sh             # EduPing 노트북 (단일) — OpenArm + 비전 + eduping_* 응용
│   └── device-noriarm.sh             # NoriArm 노트북 (단일) — OMX + 비전 + noriarm_* 응용
│
├── ui/
│   ├── robot-ui/                     # Vue 3 + Vite 단일 코드베이스 (eduping/gogoping/noriarm 분기)
│   │   ├── src/
│   │   │   ├── common/               # 호출어·STT·TTS·표정 (three.js 셰이더 ShaderFace.vue)·모드 셀렉터·자연어 디스패처·인접 정지 표시기
│   │   │   ├── composables/          # useSTT·useTTS·useVoiceController·useIntentDispatch
│   │   │   ├── stores/               # voice·mode (Pinia)
│   │   │   ├── config/               # robots.ts (VITE_ROBOT 분기)
│   │   │   ├── eduping/              # 등원·하원·율동·가게놀이·정리정돈·무궁화꽃 (defineAsyncComponent)
│   │   │   ├── gogoping/             # 보조·숨바꼭질·자장가 + 지도 위젯
│   │   │   └── noriarm/              # 블럭쌓기·정리
│   │   ├── public/
│   │   │   └── audio/                # mp3 (율동·자장가·무궁화꽃 노래)
│   │   ├── mock/                     # vite plugin: /api/* mock (Control Service 붙기 전 임시)
│   │   ├── package.json
│   │   └── vite.config.ts
│   ├── portal-ui/                    # Vue 3 + Vite (학부모·교사 공용 웹앱)
│   │   ├── src/
│   │   ├── package.json
│   │   └── vite.config.ts
│   └── admin-ui/                     # PyQt5 데스크톱 앱 (로봇 관제 전용)
│       ├── admin_app/
│       │   ├── views/                # 로봇 상태 대시보드·보조 모드 제어 UI
│       │   └── api/                  # requests Session + websocket-client
│       └── pyproject.toml
│
├── server/
│   ├── control/                      # FastAPI + rclpy + fastapi-users
│   │   ├── main.py                   # REST 엔드포인트 (Robot UI 진입점)
│   │   ├── config.py                 # env 설정 (AI Hub URL 등)
│   │   ├── ws.py                     # (TBD) /ws/robot-state
│   │   ├── ros_bridge.py             # (TBD) rclpy 게이트웨이
│   │   ├── auth.py                   # (TBD) fastapi-users
│   │   ├── jobs.py                   # (TBD) ai_job enqueue
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   ├── ai/                           # FastAPI api 프로세스 + worker 프로세스
│   │   ├── hub.py                    # api 프로세스 (의도 분류 동기)
│   │   ├── llm.py                    # Ollama 호출 (의도 분류 + 보고서)
│   │   ├── config.py                 # env 설정
│   │   ├── robots.py                 # 로봇별 모드 카탈로그
│   │   ├── worker.py                 # (TBD) ai_job 폴링
│   │   ├── vision/                   # (TBD) 얼굴 인식
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   └── db/                           # PostgreSQL + MinIO 데이터 계층
│       ├── db_models/                # 공유 SQLAlchemy 모델 (control/ai 둘 다 import)
│       │   ├── child.py              # child / parent / teacher / 매핑
│       │   ├── attendance.py
│       │   ├── photo.py              # photo + photo_subject
│       │   ├── report.py
│       │   ├── menu.py
│       │   ├── mode.py               # mode_history (robot_id 포함)
│       │   ├── nav.py                # nav_graph
│       │   ├── ai_job.py
│       │   └── session.py            # user_session
│       ├── migrations/               # alembic
│       ├── seed/                     # 31일치 menu, named pose 카탈로그
│       ├── postgres/                 # init.sql, role/extension
│       ├── minio/                    # bucket init script (photos 버킷)
│       └── pyproject.toml
│
├── device/                                # ROS2 워크스페이스 (vendor = git submodule + apt 혼합)
│   ├── eduping_ws/src/                    # EduPing 노트북에서 빌드
│   │   ├── (OpenArm SDK)                  # vendor — git submodule 위치/URL 미정
│   │   ├── eduping_bringup/               # launch / config
│   │   ├── eduping_modes/                 # 등원·하원·율동·가게놀이·정리정돈·무궁화꽃
│   │   ├── eduping_vision/                # 얼굴·객체·감정 인식 + 자연 촬영
│   │   └── eduping_msgs/
│   │
│   ├── gogoping_ws/src/                   # GogoPing 라즈베리파이 + 노트북에서 빌드 (launch 분리)
│   │   ├── vic_pinky/                     # vendor (git submodule, pinklab-art/vic_pinky) — 모바일 베이스
│   │   ├── sllidar_ros2/                  # vendor (git submodule, Slamtec) — RPLiDAR C1 드라이버
│   │   ├── open_manipulator/              # vendor (git submodule, ROBOTIS) — Pinky 로봇팔
│   │   ├── py_trees_ros/                  # vendor (git submodule, splintered-reality) — Behavior Tree
│   │   ├── py_trees_ros_interfaces/       # vendor (git submodule) — BT 메시지/서비스 정의
│   │   ├── py_trees_ros_viewer/           # vendor (git submodule) — BT 실시간 시각화
│   │   └── gogoping/                      # 우리 app 코드 그룹 (vendor 와 분리)
│   │       ├── gogoping_bringup/          # launch 통합 진입점 (namespaced)
│   │       │   └── launch/
│   │       │       ├── pi.launch.py       # 라즈베리파이용 (vicpinky_bringup + sllidar + camera)
│   │       │       └── laptop.launch.py   # 노트북용 (Nav2 + modes + vision)
│   │       ├── gogoping_camera/           # USB 카메라 → UDP MJPEG 송출 (SR-CAM-001)
│   │       ├── gogoping_camera_pan/       # Arduino 서보 (pyserial, UI/BT 양쪽 사용, 우선순위 토픽 분리)
│   │       ├── gogoping_navigation/       # Nav2 wrapper (params + maps + launch)
│   │       ├── gogoping_vision/           # YOLO / ReID(Deep SORT, OSNet) / face_recognition
│   │       ├── gogoping_msgs/             # ROS .msg/.srv/.action 정의 (ament_cmake)
│   │       └── gogoping_modes/            # 로봇 매니저 — FSM + Behavior Tree
│   │           └── gogoping_modes/
│   │               ├── __init__.py
│   │               ├── main.py            # rclpy.init + Node + FSM 인스턴스화 + spin
│   │               ├── context.py         # 공유 객체 저장소 (blackboard, interfaces, fsm 핸들)
│   │               │
│   │               ├── fsm/                          # 상태머신
│   │               │   ├── robot_fsm.py              # 6 states + transition 규칙
│   │               │   └── states/                   # 각 state 의 lifecycle (on_enter / on_exit)
│   │               │       └── <state_name>_state.py # charging / idle / assist / play / returning / error
│   │               │
│   │               ├── bt/                           # Behavior Tree (py_trees)
│   │               │   ├── blackboard.py             # 공유 변수 스키마 + 초기값 (Keys 상수, 권한 등록)
│   │               │   │
│   │               │   ├── behaviors/                # 개별 BT 노드 (Action / Condition)
│   │               │   │   │                         # ※ 기본 .py 단일 파일, 복잡해지면 폴더로 전환 (컨벤션 참조)
│   │               │   │   │
│   │               │   │   ├── common/               # 모든 MainTree 공유 가드 + 분기 condition
│   │               │   │   │   └── <behavior>.[py|/] # battery_full_monitor / battery_low_monitor /
│   │               │   │   │                         # hardware_health_monitor / collision_event_handler /
│   │               │   │   │                         # command_listener / docking_contact_check /
│   │               │   │   │                         # check_task / check_carry_mode
│   │               │   │   │
│   │               │   │   ├── navigation/           # Nav2 호출 + 도킹 시퀀스
│   │               │   │   │   └── <behavior>.[py|/] # navigate_to_pose / align_to_dock [스켈레톤] /
│   │               │   │   │                         # approach_dock [스켈레톤] / verify_docking_contact [스켈레톤] /
│   │               │   │   │                         # stop_base / maintain_distance / check_arrival
│   │               │   │   │
│   │               │   │   ├── perception/           # gogoping_vision 토픽 → blackboard 어댑터
│   │               │   │   │   └── <behavior>.[py|/] # is_target_visible / detect_target_person /
│   │               │   │   │                         # found_child / child_face_tracker / load_stability_check
│   │               │   │   │
│   │               │   │   ├── follow/               # 카메라 pan 제어 + 추종 관련
│   │               │   │   │   └── <behavior>.[py|/] # face_tracking / wait_for_reappear /
│   │               │   │   │                         # raise_camera_pan / pan_camera_sweep
│   │               │   │   │
│   │               │   │   ├── manual/               # 수동 모드 lifecycle
│   │               │   │   │   └── <behavior>.[py|/] # enable_manual_control / wait_for_exit
│   │               │   │   │
│   │               │   │   └── recovery/             # 에러 처리
│   │               │   │       └── <behavior>.[py|/] # stop_all_motors / notify_admin_ui / log_error_to_db
│   │               │   │
│   │               │   └── trees/                    # BT 트리 조립 (한 파일 = 한 트리 전체)
│   │               │       ├── main_trees/           # FSM state 별 MainTree (총 6개)
│   │               │       │   └── BT_<state>_main.py    # charging / idle / assist / play / returning / error
│   │               │       │
│   │               │       └── sub_trees/            # 작업별 SubTree (총 5개)
│   │               │           └── BT_<task>_sub.py      # carry / follow / lullaby / hide_and_seek / return
│   │               │
│   │               ├── interfaces/                   # 외부 HW / ROS action·service·topic 호출 래퍼
│   │               │   └── <iface_name>.py           # nav2_client / camera_pan_client / ui_publisher /
│   │               │                                 # battery_subscriber / collision_subscriber / db_logger
│   │               │
│   │               └── utils/                        # 공통 helper (Rule of Three 적용 시 채움)
│   │
│   └── noriarm_ws/src/                    # NoriArm 노트북에서 빌드
│       ├── open_manipulator/              # vendor (git submodule, robotis-git/open_manipulator) — OMX
│       ├── noriarm_bringup/
│       ├── noriarm_modes/                 # 블럭쌓기·정리
│       ├── noriarm_vision/
│       └── noriarm_msgs/
│
└── train/                            # lerobot ACT 학습
    ├── lerobot_act/                  # 학습 스크립트 wrapper
    ├── data/                         # .gitignore (텔레오퍼레이션 raw, GB 단위)
    ├── checkpoints/                  # .gitignore (배포 시 device/<robot>_ws/src/<pkg>/policies/ 로 복사)
    ├── pyproject.toml
    └── README.md
```

## 컴퓨터 분담

| 로봇 | 컴퓨터 | 책임 |
|---|---|---|
| GogoPing | 라즈베리파이 | `vicpinky_bringup` — 모터 드라이버 + RPLiDAR (USB 시리얼 직결) |
| GogoPing | 노트북 | Nav2/SLAM + `gogoping_*` 응용 + 비전 |
| EduPing | 노트북 단독 | OpenArm USB 직결 + 비전 + `eduping_*` 응용 |
| NoriArm | 노트북 단독 | OMX USB 직결 + 비전 + `noriarm_*` 응용 |
| Control / AI Server | 별도 호스트 (docker-compose) | control + ai + postgres + minio |
| Portal UI | 학부모·교사 모바일/PC | 같은 Wi-Fi LAN IP 로 접근 (Vite dev) |
| Admin UI | 관리자 PC | PyQt5 데스크톱 앱 |

GogoPing 의 라즈베리파이와 노트북은 같은 `ROS_DOMAIN_ID` 로 토픽을 공유한다.

## 동기화 규칙

- `docs/` 의 frontmatter (`confluence_page_id` 등) 는 직접 편집 금지 (pull/push 스크립트가 갱신)
- `.assets/` 디렉토리는 매 동기화마다 재생성
- 자세한 규칙: [docs/CLAUDE.md](CLAUDE.md)

## 스크립트 사용 예

```bash
# Confluence 동기화
scripts/pull_docs.sh                       # 대화형 메뉴
scripts/pull_docs.sh a                     # 전체 pull
scripts/push_docs.sh 2 --apply             # 2번 페이지 push

# 서버
scripts/run_server.sh                      # tmux 세션 (postgres + pgweb + AI Hub + Control)
scripts/stop_server.sh                     # docker compose down
scripts/db-seed.sh                         # 마이그레이션 + seed

# UI
scripts/ui-robot.sh eduping                # 또는 gogoping / noriarm
scripts/ui-portal.sh
scripts/ui-admin.sh

# 디바이스 1회 셋업 — README 의 단계별 명령 (apt install + git submodule init + colcon build) 을 따라 수동 실행

# 디바이스 (매 실행 — ros2 launch)
scripts/device-gogoping-pi.sh              # 라즈베리파이에서
scripts/device-gogoping-laptop.sh          # GogoPing 노트북에서
scripts/device-eduping.sh                  # EduPing 노트북에서
scripts/device-noriarm.sh                  # NoriArm 노트북에서
```
