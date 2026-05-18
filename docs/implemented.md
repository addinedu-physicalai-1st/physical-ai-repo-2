# 구현 완료 (Implemented)

이 문서는 [implementation-plan.md](implementation-plan.md) 에서 **완전히** 구현이 끝난 SR 을 옮겨 둔 곳이다. 이동 규칙은 루트 [CLAUDE.md](../CLAUDE.md) 의 "구현 완료 항목 관리" 섹션 참조.

부분 구현 (UI 만 완료, ROS2 publish 남음 등) 은 옮기지 않는다 — 모든 부분이 끝났을 때 한 번에 이동.

## 1. EduPing UI

### 1.1 율동 안내

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-PLAY-002 | 율동 재생 | EduPing UI 의 동요 리스트 (Robot UI 코드베이스의 정적 `dance_songs.json` — 제목·길이·trajectory ID·mp3 경로 메타) 에서 곡을 선택하면 EduPing UI (브라우저 `<audio>`) 가 `public/audio/` 의 mp3 를 재생하고 EduPing(OpenArm 양팔) 이 EduPing ROS2 패키지 내부에 사전 녹화로 둔 trajectory 를 같은 시점에 재생한다 (Control Server REST 로 trajectory ID 전달 후 동기 시작). | High | `ui/robot-ui/src/eduping/{DanceManager,RecorderControls}.vue`, `server/control/eduping/{router,ros_bridge}.py` (`/api/eduping/dance/{slug}/play`) | 2026-05-13 |

## 2. GogoPing UI

### 2.5 자장가

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-NAP-001 | 자장가 재생 | GogoPing UI (브라우저 `<audio>`) 가 사전 등록된 자장가 mp3 1곡을 재생한다. 종료는 §8.2 명령 인터페이스 (호출어 + 자연어 모드 전환) 로 처리. | High | `ui/robot-ui/src/composables/useModeAudio.ts`, `ui/robot-ui/public/audio/lullaby.mp3` | 2026-05-04 |

### 2.7 카메라 영상 스트리밍

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-CAM-001 | 카메라 송출 (Pi, default ON) | Vic Pinky 가 ROS2 패키지 `gogoping_camera` 의 `camera_streamer_v4l2` (default, linuxpy 직접) 또는 `camera_streamer` (cv2 fallback) 실행 시 자동으로 USB 웹캠을 MJPEG 640×480 q60 @ 25fps 으로 캡처해 Control Server (port 9013/UDP, primary stream = role 3) 로 28B 헤더 (magic "PING" + version + robot_id + stream_id + frame_seq + ts_ms + jpeg_size + CRC32) + JPEG payload 의 단일 패킷 = 단일 frame 형식으로 항상 송신한다. Control Server 의 수동 STOP 신호 (Pi 측 listener port 9012/UDP = role 2, intent_seq 포함) 수신 시 송출을 중지하고, START 신호 수신 시 재개한다. 자동 트리거 (subscriber 카운트 기반) 는 없음. EduPing/NoriArm 도 동일 프로토콜 (영상 9023/9033, 제어 9022/9032). bringup 통합: `gogoping_bringup/launch/pi.launch.py` 가 `gogoping_camera/launch/camera_stream.launch.py` 를 IncludeLaunchDescription 으로 포함 — `scripts/device-gogoping-pi.sh` 실행 시 자동 시작/종료. 부팅 자동 시작 (systemd) 은 별도 SR. | High | `device/gogoping_ws/src/gogoping/gogoping_camera/gogoping_camera/{streamer,streamer_v4l2}.py` | 2026-05-11 |
| SR-CAM-002 | Control Server 스트리밍 게이트웨이 | Control Server 가 별도 uvicorn 프로세스 (port 8100/TCP) 로 `/ws/video-stream` WebSocket 엔드포인트를 노출한다 (SR-ADM-001 의 `/ws/<channel>` 컨벤션). 로봇별 UDP 수신 스레드가 frame 을 받아 magic/길이/CRC32/frame_seq 4단계 검증 후 asyncio 측 frame hub 에 전달, **subscriber 가 있는 영상만 client 큐(maxsize=1)에 push, 0 명이면 즉시 drop**. fastapi-users 세션 쿠키 핸드셰이크 인증, 30초 heartbeat, drop-oldest 정책. Server 부팅 시 5초간 Pi frame 수신 모니터, 미수신 시 START 1회 송신해 Pi sanity check. | High | `server/control/streaming/{app,udp_receiver,frame_hub,ws_router,auth,protocol,config}.py` | 2026-05-11 |
| SR-CAM-003 | 다중 클라이언트 / 다중 로봇 | Client 가 uuid client_id 로 hello 후 robot 별 subscribe/unsubscribe 메시지로 영상 fan-out 을 토글할 수 있다. 한 client 가 여러 로봇 동시 구독 가능 (multi-subscribe), stream 필드(기본 0=primary)로 로봇당 여러 카메라 선택 가능. subscribe/unsubscribe 는 server 측 fan-out 정책만 변경, Pi 송출에는 영향 없음 (실시간 전환 ~30–50ms). | High | `server/control/streaming/{ws_router,client_registry,frame_hub}.py` | 2026-05-11 |
| SR-CAM-004 | Admin UI 카메라 위젯 | Admin UI 가 `websockets.sync.client` 기반 WS 클라이언트를 1개 유지하고, GogoPing/NoriArm/EduPing 대시보드 카드 표시·은닉 이벤트에 맞춰 subscribe/unsubscribe 를 송신한다. 받은 바이너리 frame 을 robot_id/stream_id 로 라우팅해 `QLabel` 에 표시. 끊기면 1초 후 자동 재연결 후 활성 구독 자동 복원 ([teleop_client.py](../ui/admin-ui/services/teleop_client.py) 패턴 일치). | High | `ui/admin-ui/widgets/camera_widget.py` | 2026-05-11 |
| SR-CAM-005 | 수동 admin 제어 (정비/절전) | Admin UI 또는 Control Server 의 admin 라우터가 명시적 액션으로 특정 Pi 의 송출을 STOP/START 시킬 수 있다 (정비 모드, 야간 절전 등). REST `POST /api/streaming/robots/{robot}/stop` 및 `POST /api/streaming/robots/{robot}/start` (`/api/` prefix 컨벤션). 이 액션은 subscriber 카운트와 무관하게 Pi 의 streaming_enabled 플래그만 토글한다 (intent_seq 단조 증가, 1초 간격 3회 재전송). | Low | `server/control/streaming/{admin_router,robot_controller}.py` | 2026-05-11 |
| SR-CAM-006 | 카메라 pan/tilt 서보 제어 | GogoPing 의 USB 웹캠을 Arduino Uno + MG995 ×2 (pan D9 / tilt D10) 로 2축 제어한다. 시리얼 (`/dev/arduino-camera` udev 심볼릭, 115200 baud) 프로토콜은 라인 단위 `PT:<pan>,<tilt>\n` / `OK:<pan>,<tilt>\n`. 펌웨어 watchdog 이 1000ms 무명령 시 (90,90) 복귀해서 ROS 노드 `servo_bridge` 가 `~/cmd_pan`·`~/cmd_tilt` (Float32 deg) 구독 → clamp (pan 5~175°, tilt 30~150°) + rate_limit + 20Hz state 재송신 → `~/state` (JointState, `camera_pan_joint`·`camera_tilt_joint`) publish. `keyboard_teleop` (raw stdin: a/d=pan, w/s=tilt, space=center, [/]=step 조절) 와 자동 sweep 용 `pan_scanner` 노드 (teleop 과 동시 사용 X) 제공. Control Server (`/camera_pan/cmd` POST + `/camera_pan/state` WS) 와 Admin UI `CameraPanCard` (글로벌 단축키 W/A/S/D=pan·tilt, C=center; 카드 포커스 시 화살표·Space) 로 원격 제어. 외부 5–6V/1A 전원 + Arduino GND 공통 필수. | Mid | `controller/gogoping-controller/src/gogoping/gogoping_camera_pan/{servo_bridge,keyboard_teleop,pan_scanner,protocol}.py`, `controller/gogoping-controller/src/gogoping/gogoping_camera_pan/firmware/servo_bridge/servo_bridge.ino`, `service/control-service/control_service/camera_pan/{ros_bridge,router}.py`, `app/admin-app/widgets/camera_pan_card.py`, `app/admin-app/services/camera_pan_client.py` | 2026-05-18 |

## 7. AI Server

### 7.4 음성 처리

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-VOICE-002 | 음성 인식 (STT) | 각 로봇 UI (브라우저) 가 Web Speech API (`webkitSpeechRecognition`, ko-KR) 로 음성을 텍스트로 변환한다 (클라이언트 측, 서버 STT 미사용). | High | `ui/robot-ui/src/composables/useSTT.ts` | 2026-05-04 |
| SR-VOICE-003 | 의도 분류 | AI Server 가 의도 분류 LLM 으로 텍스트의 의도(모드 전환 / 모드 내 서브 명령)를 분류한다. 분류되지 않는 발화는 무시한다. | High | `server/ai/{hub,llm}.py` (Ollama qwen2.5:3b) | 2026-05-04 |
| SR-VOICE-004 | 잡담 응답 | AI Hub 가 SR-VOICE-003 의도 분류 결과가 mode_change·sub_command 어디에도 해당하지 않을 때 잡담 전용 Ollama 모델 (`ollama_chat_model`, 기본 `qwen2.5:3b`) 으로 한국어 1~2문장 자연어 응답을 생성해 `/api/voice/intent` 응답에 `{kind: "chat", reply: "..."}` 로 돌려주고, 로봇 UI 가 받은 reply 를 SR-VOICE-005 TTS 로 음성 출력한다. 모드·구동기 상태는 변경하지 않는다. 응답 LLM 호출이 실패하면 `{kind: "ignored"}` 로 graceful fallback 한다. | High | `server/ai/{hub,llm,prompts,config}.py` (`generate_chat`, `ollama_chat_model`) | 2026-05-13 |
| SR-VOICE-005 | 음성 출력 (TTS) | 각 로봇 UI (브라우저) 가 `window.speechSynthesis` API (ko-KR voice) 로 응답 텍스트를 음성으로 출력한다 (클라이언트 측, 서버 TTS 미사용). | High | `ui/robot-ui/src/composables/useTTS.ts` | 2026-05-04 |

## 8. 다중 UI 공통

### 8.2 명령 인터페이스

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-VOICE-007 | 호출어 인식 | 각 로봇 UI 가 Web Speech API STT 항상 듣기 모드로 텍스트 스트림을 모니터링하다 자기 이름 호출어("에듀핑" / "고고핑" / "노리암") 단어 매칭 시 즉시 진행 중인 동작을 일시 정지하고 음성으로 대답한 뒤 후속 명령 수신 윈도우 (5초) 를 활성화한다. 호출어와 명령이 같은 발화에 포함된 경우 (예: "에듀핑, 정리정돈 시작해") 는 호출어 직후 텍스트를 그대로 명령으로 처리하고 별도 윈도우 대기 없이 즉시 의도 분류로 전달한다. | High | `ui/robot-ui/src/composables/useVoiceController.ts` | 2026-05-04 |
| SR-UI-003 | 음성·타이핑 모드 토글 / 음성 시각 피드백 / barge-in | Robot UI 하단 영역이 voice store 의 `voiceMode: 'voice' \| 'text'` 토글 상태에 따라 두 가지로 분기된다. ① **text 모드** — 기존 `CommandBar`(입력창 + 전송 버튼) 노출, 호출어 없이 타이핑한 명령을 즉시 dispatch (`useVoiceController.processCommand` 의 wake-word-bypass 경로). STT 는 정지. ② **voice 모드** — STT 가 항상 떠 호출어 대기, `listening`(호출어 감지 후 5초 윈도우) 동안 Siri-like 몽글몽글 애니메이션(`SiriBlob.vue` — 색 블롭 3개를 morphing border-radius + translate keyframe 으로 흐르게 하고, `useAudioLevel` composable 이 `getUserMedia` + `AnalyserNode` 로 마이크 RMS 레벨을 받아 블롭 wrapper 의 transform scale 에 반영) + STT 인식 텍스트 자막(`VoiceCaption.vue`) 표시, `dispatching` 동안 dot wave 로딩(`DispatchingLoader.vue`) + 마지막 발화 자막 표시. 진행 중 호출어가 다시 들리면 `AbortController` 로 in-flight `/api/voice/intent` fetch 를 abort + `tts.cancel()` 후 즉시 새 `wake_detected` 로 전환 (barge-in). `useVoiceController` 의 호출어 매칭 게이트를 `idle` 외 모든 상태로 확장. 모드 토글 버튼은 하단 영역 우측에 마이크/키보드 아이콘으로 노출. | High | `ui/robot-ui/src/composables/{useVoiceController,useAudioLevel}.ts`, `ui/robot-ui/src/common/{SiriBlob,VoiceCaption,DispatchingLoader,CommandBar}.vue` | 2026-05-12 |

### 8.3 표정 상시 표시

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-UI-001 | 표정 상시 표시 | 각 로봇 UI 가 표정 (basic·hello·happy·fun·interest·bored·sad·angry·sleep) 을 현재 모드·이벤트에 따라 디스플레이에 상시 표시한다. three.js 셰이더로 눈·눈썹·입 파라미터를 합성. | High | `ui/robot-ui/src/common/EmotionDisplay.vue`, `ui/robot-ui/src/common/ShaderFace.vue` | 2026-05-04 |

## 4. Admin UI (PyQt5 데스크톱 앱, 로봇 관제)

### 4.5 nav graph 편집

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-ADM-006 | nav graph 편집 UI | Admin UI 가 SLAM 맵 + nav graph 위에서 노드/간선을 시각적으로 편집한다. 편집 모드 토글 시 노드 추가 (좌클릭-드래그 화살표 + 이름 팝업), 노드 이동 (드래그 → 화살표 미리보기 → 클릭), 1-step undo, 간선 잇기 (노드 2회 클릭) / 끊기 (간선 클릭 + Delete), 거리 threshold 기반 자동 간선, 기본값 snapshot 으로 초기화/갱신을 제공한다. 호버 하이라이트로 클릭 타겟 시각화. 변경은 yaml atomic write + graph_router reload 로 즉시 적용. nav2 이동 중에는 편집 모드 진입 차단 + 자동 이탈. | High | `ui/admin-ui/widgets/waypoint_map_card.py`, `server/control/waypoints/router.py`, `server/control/waypoints/yaml_store.py`, `server/control/waypoints/ros_bridge.py`, `device/gogoping_ws/src/gogoping/gogoping_navigation/gogoping_navigation/graph_router_node.py`, `device/gogoping_ws/src/gogoping/gogoping_navigation/gogoping_navigation/graph.py`, `device/gogoping_ws/src/gogoping/gogoping_navigation/config/waypoints.default.yaml`, `device/gogoping_ws/src/gogoping/gogoping_navigation/config/lanes.default.yaml` | 2026-05-15 |

## 5. Portal Web (학부모·교사 공용 웹앱)

### 5.1 교사 — 등록

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-REG-001 | 자녀 정보 입력 | Portal Web 등록 폼이 자녀의 이름·생년월일·반을 입력받아 모델 객체로 변환한다. | High | `ui/portal-ui/src/components/teacher/RegisterWizard.vue`, `server/control/routers/children.py` | 2026-05-05 |
| SR-REG-002 | 학부모 정보 입력 | Portal Web 등록 폼이 자녀에 연결되는 학부모의 이름·이메일·연락처를 입력받아 자녀와 함께 한 트랜잭션으로 처리한다. 등록 시 초기 비밀번호를 자동 생성해 학부모 계정을 발급한다. | High | `ui/portal-ui/src/views/teacher/Register.vue`, `server/control/routers/parents.py` | 2026-05-05 |
| SR-REG-003 | 입력 검증 | Portal Web 이 입력 검증으로 학부모·자녀 정보의 패턴·필수값·중복을 검증한다. | High | `ui/portal-ui/src/components/teacher/RegisterWizard.vue` (client), `server/control/schemas.py` (server Pydantic) | 2026-05-05 |

### 5.2 교사 — 출결

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-OPS-002 | 출결 보드 표시 | Portal Web 이 Control Service REST 로 attendance 를 조회해 갱신 표시한다. | High | `ui/portal-ui/src/views/teacher/Dashboard.vue`, `server/control/routers/attendance.py` | 2026-05-05 |

### 5.3 교사 — 정보 보기

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-OPS-014 | 점심메뉴 보기 | Portal Web 이 DB `menu` 테이블을 조회해 달력 월간 위젯의 각 day-of-month 셀에 seed 메뉴를 매칭 표시한다. | Low | `ui/portal-ui/src/components/common/MenuCalendar.vue`, `server/control/routers/menu.py` | 2026-05-05 |
| SR-OPS-016 | 학부모 정보 보기 | Portal Web 이 DB parent + parent_child 매핑을 조회해 자녀별 학부모 (이름·이메일·연락처) 를 표시한다. | Low | `ui/portal-ui/src/views/teacher/Children.vue`, `server/control/routers/children.py` | 2026-05-05 |
| SR-OPS-017 | 자녀 일일 보고서 보기 | Portal Web 이 DB report 테이블을 조회해 자녀별 일자별 일과 보고서를 표시한다. | Low | `ui/portal-ui/src/views/teacher/Reports.vue`, `server/control/routers/reports.py` | 2026-05-05 |
| SR-OPS-018 | 자녀 일일 보고서 편집 | Portal Web 이 표시된 보고서 텍스트를 인라인 편집해 DB report 테이블에 UPDATE (body, edited_at) 한다. | Low | `ui/portal-ui/src/components/teacher/ReportEditor.vue`, `server/control/routers/reports.py` | 2026-05-05 |

### 5.4 학부모 — 로그인·계정

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-PAR-006 | 학부모 로그인 | Portal Web 이 이메일 + 비밀번호로 학부모 계정 로그인을 처리한다 (초기 비밀번호는 등록 시 자동 발급). | High | `ui/portal-ui/src/views/parent/Login.vue`, `server/control/auth.py` (fastapi-users cookie) | 2026-05-05 |
| SR-PAR-007 | 비밀번호 변경 | Portal Web 이 학부모의 비밀번호 변경 요청을 받아 DB 에 저장한다. | Low | `ui/portal-ui/src/views/parent/Settings.vue`, `server/control/auth.py` (`UserManager._update`) | 2026-05-05 |

### 5.5 학부모 — 자녀 선택

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-PAR-008 | 자녀 선택 | Portal Web 이 로그인한 학부모에 매핑된 자녀(다수) 리스트를 표시하고, 조회할 자녀를 선택한다. | High | `ui/portal-ui/src/components/parent/ChildSelector.vue`, `server/control/routers/children.py` | 2026-05-05 |

### 5.6 학부모 — 등·하원 조회

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-PAR-001 | 등·하원 조회 | Portal Web 이 선택된 자녀의 등·하원 상태를 DB 조회로 표시한다. | Low | `ui/portal-ui/src/views/parent/Attendance.vue`, `server/control/routers/attendance.py` | 2026-05-05 |

### 5.7 학부모 — 메뉴

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-PAR-004 | 점심메뉴 조회 | Portal Web 이 달력 월간 위젯의 각 day-of-month 셀에 seed 메뉴를 매칭 표시한다. | Low | `ui/portal-ui/src/views/parent/Menu.vue`, `server/control/routers/menu.py` | 2026-05-05 |

### 5.9 학부모 — 일과 보고서 조회

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-RPT-002 | 학부모 보고서 조회 | Portal Web 이 선택된 자녀의 하루 일과 보고서 (교사 편집 반영된 최종본) 를 일별로 표시한다. | Low | `ui/portal-ui/src/views/parent/Report.vue`, `server/control/routers/reports.py` | 2026-05-05 |

## 6. Control Server / DB (백엔드)

### 6.1 등록 / 인증

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-REG-004 | 등록 저장 | Control Server가 검증된 정보를 PostgreSQL 트랜잭션 INSERT 로 저장하고 AUTO_INCREMENT 식별자를 반환한다. | High | `server/control/routers/{children,parents}.py` (트랜잭션 commit + AUTO_INCREMENT 반환) | 2026-05-05 |
| SR-REG-007 | 학부모-아이 매핑 | Control Server가 parent_child 매핑 테이블에 외래키 INSERT 로 학부모·자녀 관계를 저장한다. | High | `server/control/routers/parents.py` (parent_child INSERT) | 2026-05-05 |
| SR-REG-008 | 사용자 접근 권한 발급 | Control Server (fastapi-users + DatabaseStrategy) 가 학부모·교사 계정 로그인에 세션을 발급하고 HttpOnly 쿠키 (`SameSite=Lax`) 로 전달한다. 학부모는 브라우저 쿠키, 교사앱(PyQt5)은 `requests.Session()` cookie jar 로 유지. 세션 토큰은 Postgres `user_session` 테이블에 저장한다. | High | `server/control/auth.py` (fastapi-users CookieTransport + DatabaseStrategy + access_token 테이블) | 2026-05-05 |
| SR-REG-009 | 아이-교사 매핑 | Control Server가 child_teacher 매핑 테이블에 외래키 INSERT 로 아이·담당 교사 관계를 저장한다. | High | `server/control/routers/children.py` (child_teacher INSERT) | 2026-05-05 |

### 6.5 데이터 모델

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-DAT-001 | 자녀·학부모·교사 정보 저장 | DB 가 공유 SQLAlchemy 모델 패키지의 ORM ER 설계로 child·parent·teacher·user_session 테이블 + 매핑 테이블을 저장하며, Control Server·AI Server 가 동일 패키지를 import 해 단일 진실의 모델을 공유한다. | High | `server/db/models/{user,child}.py`, `server/db/alembic/versions/0001_init.py` | 2026-05-05 |
| SR-DAT-003 | 출결 기록 | DB 가 attendance(child_id, time, type) 테이블에 등·하원 시각을 기록한다. | High | `server/db/models/attendance.py` (UNIQUE child_id+date+type) | 2026-05-05 |
| SR-DAT-007 | 점심메뉴 | DB 가 `menu(day, items)` 테이블 (PK: `day` 1~31) 에 31일치 점심메뉴를 seed 데이터로 저장한다. 어떤 월이든 day-of-month 로 매칭하므로 월별 입력 UI 는 별도로 두지 않는다. | Low | `server/db/models/menu.py`, `server/db/seed.py` (5종 sample 31일 순환) | 2026-05-05 |
| SR-DAT-014 | 일과 보고서 데이터 | DB 가 report(child_id, date, body, generated_at, edited_at) 테이블에 자녀별 일자별 일과 보고서를 저장한다. UNIQUE(child_id, date) 제약으로 중복 생성을 방지한다. | Low | `server/db/models/report.py` (UNIQUE child_id+date) | 2026-05-05 |
