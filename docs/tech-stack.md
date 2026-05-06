# Tech Stack

각 추상 동사·컴포넌트가 어떤 라이브러리·모델·버전으로 구현되는지 매핑. SR / Design 본문은 추상 동사만 사용하고, 구체 구현체는 이 문서를 참조한다.

## 1. 백엔드 컴포넌트

| 컴포넌트 | 스택 | 비고 |
| --- | --- | --- |
| Control Server | Python 3.11 + rclpy + FastAPI + SQLAlchemy + fastapi-users (DatabaseStrategy, HttpOnly 쿠키 `SameSite=Lax`) | ROS2 게이트웨이, 브라우저 UI 용 REST/WS (rosbridge 와 별개), 학부모 인증·세션 (Postgres `user_session` 테이블). 발표용 개발 환경이라 별도 어드민 UI 없음, presigned URL 발급도 Control Server 일원화 |
| Parent UI | Vue 3 + Vite (dev server 단독, `vite dev` 로 운영) + Pinia — `server.proxy` 로 `/api/*` → Control Service, `/photos/*` → MinIO | 학부모 단독 웹앱. Flask·Nginx 미사용 (개발 전용). 학부모 모바일은 같은 Wi-Fi LAN IP 로 접근 |
| Educator UI | Python 3.11 + PyQt5 + requests (`Session()` cookie jar) + websocket-client + cv2/QCamera — 데스크톱 앱 | 교사 운영용 데스크톱 앱. Control Service REST + WebSocket (`/ws/robot-state` 로 로봇 상태 실시간 수신, SR-OPS-019) 경유. rclpy 직접 호출 안 함. fastapi-users 의 HttpOnly 쿠키 인증을 `requests.Session()` 으로 유지하고 같은 쿠키를 WebSocket handshake 헤더로 전달. MinIO presigned URL 은 `requests.get(url)` 직접 GET (proxy 불필요). 카메라 캡처 (등록 15장) 는 cv2 또는 QCamera, 지도 위젯 (SLAM 맵 + nav graph) 은 QGraphicsView + QPixmap |
| Robot UI | Vue 3 + Vite dev server (Chromium kiosk) + Pinia + Web Speech API (STT/TTS) + three.js (셰이더 표정) — **단일 코드베이스**, 각 로봇 노트북에서 `VITE_ROBOT=eduping/gogoping/noriarm` env 로 분기 인스턴스 실행. `server.proxy` 로 `/api/*` → Control Service | 공통 composables/components (~50%): 호출어 감지·STT·TTS·표정 (three.js 셰이더 — `ShaderFace.vue`)·모드 셀렉터·자연어 명령 디스패처·인접 정지 표시기. 로봇별 모드 화면 (~50%) 은 `defineAsyncComponent` 로 분기 인스턴스에서만 lazy load. GogoPing 지도 위젯 (Canvas + PGM/PNG 맵 + nav graph 좌표 오버레이) 은 GogoPing 인스턴스에서만 활성. 자연 촬영은 ROS2 노드가 단독 처리하므로 UI 미관여. Nginx 미사용 (개발 전용) |
| AI Server | Python 3.11 + FastAPI + httpx + (얼굴 인식) + (LLM SDK) | Vision · Intent · LLM 라우팅 (STT/TTS 는 브라우저 UI 의 Web Speech API 가 처리하므로 서버에 없음), api 프로세스 (의도 분류 동기) + worker 프로세스 (`ai_job` 큐 폴링), 단일 코드베이스, 재시작 시 `running → pending` 일괄 reset |
| LLM | Ollama + Qwen 3 4B (호스트 네이티브 설치 — 컨테이너 미사용) | 의도 분류 + 일과 보고서 모두 4B 단일 모델 공유. 원격 LLM (Gemini 등) 미사용 — fallback 없음. RTX 3060 6GB VRAM 에서 Q4 양자화 시 ~2.5GB 사용, vision 워크로드 (YOLO/face) 와 공존 가능. 학습용 RTX 5090 데스크탑에 별도 인스턴스로 띄워 LAN 호출도 가능 (`OLLAMA_HOST=0.0.0.0:11434`). Qwen3 의 `think=false` 옵션 사용해 의도 분류 latency 최소화 |
| DB | PostgreSQL 15 | Control 도메인 + ai_job 테이블 공유 |
| Object Storage | MinIO | 사진 binary (presigned URL 발급) |
| Inter-service | Browser → Vite dev server `server.proxy` → Control Service / MinIO (브라우저 입장 same-origin), Control → AI: HTTP POST `/jobs`, AI Hub / AI Worker → Ollama: HTTP `:11434` (호스트 네이티브, 컨테이너에서는 `host.docker.internal:11434` 또는 호스트 IP), Control / AI Server 가 공유 SQLAlchemy 모델 패키지 (예: `pingdergarten_models/`) 로 동일 PostgreSQL 접근 | Redis 미사용 |
| 개발/배포 환경 | Docker Compose (control / ai / minio / postgres) + 호스트 Ollama + 각 노트북에서 `vite dev` 실행: parent-ui (1개, Vue 3) + robot-ui (3개 인스턴스, Vue 3, `VITE_ROBOT=eduping/gogoping/noriarm` env 분기로 같은 코드베이스 실행) + 교사 PC 에서 `python -m educator_app` (PyQt5) — 노트북 16GB / RTX 3060 가능. 학습용 RTX 5090 데스크탑 별도 | 발표 시연 환경 전용 (Flask·Nginx·rosbridge 미사용). Ollama Qwen 3B 양자화 (호스트 네이티브) + 서버 측 STT/TTS 0GB (브라우저가 처리) — Whisper·Edge-TTS 미사용 |

## 2. 추상 동사 → 구현체 매핑

| 추상 동사 / 능력 | 후보 구현체 | 비고 |
| --- | --- | --- |
| 얼굴 인식 (식별·다중 임베딩) | face_recognition / DeepFace / InsightFace (buffalo_l) | 등록 N장 → child_id 별 다중 임베딩 → 매칭 시 최대 유사도 |
| Anti-spoofing (liveness) | Silent-Face-Anti-Spoofing (ONNX) / MiniFASNet | 등록·매칭 시 사진·영상 도용 차단 |
| 객체 인식 | YOLO (v8 기준) | 사람·블럭·장난감 |
| 자세 인식 (단일 인물) | MediaPipe Pose | 낙상 감지 |
| 다중 인물 자세 인식 | YOLOv8-Pose-n (RTX 3060 부하 고려, n 권장 / s 도 가능) | 무궁화꽃 참가 아이별 병렬 관절 움직임 판정. 인원 ≤ 5명 |
| 다중 인물 트래킹 | ByteTrack / BoT-SORT (얼굴 인식으로 child_id 매핑 유지) | 무궁화꽃 |
| 손 모양 인식 | MediaPipe Hand | (예비) |
| 감정 인식 | DeepFace / FER | 자연 촬영 트리거 |
| 자율 주행 | Nav2 + AMCL + DWB local planner | 지도 기반 navigation |
| 동적 장애물 회피 | Nav2 dynamic obstacle layer | 충돌 회피 |
| 사람 추적 (ReID) | YOLO + Deep SORT / OSNet | 교사 추종 |
| trajectory 실행 | MoveIt2 + OpenArm SDK / OMX SDK | 사전 녹화 trajectory 재생 |
| 모방학습 정책 | lerobot ACT (env_state token 에 task one-hot 주입으로 다중 task 통합 학습 가능, 정책 자체에 종료 신호 없음 → 외부에서 홈 pose 도달 감지 + 타임아웃 폴백으로 종료) | 가게놀이 통합 ACT 1개 (모형 3종을 env_state=[1,0,0]/[0,1,0]/[0,0,1] 로 분기, 의도 분류 LLM 결과를 env_state 로 인코딩) · 정리정돈 1개 · 블럭쌓기 1개 · 블럭 정리 1개 = 총 4개 ACT. 전 task 실물 텔레오퍼레이션 데이터로 학습 (시뮬 미사용) |
| 음성 인식 (STT) | 브라우저 Web Speech API (`webkitSpeechRecognition`, ko-KR) | 클라이언트(로봇 UI) 측 STT — 서버 메모리 0, 인터넷 의존 (Chrome 의 경우 Google STT 백엔드) |
| 음성 합성 (TTS) | 브라우저 `window.speechSynthesis` API (ko-KR voice) | 클라이언트(로봇 UI) 측 TTS — 서버 메모리 0, OS TTS 사용 (오프라인 가능) |
| 호출어 감지 | 브라우저 Web Speech API STT 항상 듣기 모드 + 텍스트 매칭 | "에듀핑" / "고고핑" / "노리암" — 별도 wake word 모델(OpenWakeWord/Porcupine) 미사용 |
| 의도 분류 LLM | 로컬 Ollama + Qwen 3 4B (rule-base 결합) | 모드 전환 / 모드 내 서브 명령 라우팅 |
| 일과 보고서 LLM | 로컬 Ollama + Qwen 3 4B (의도 분류 LLM 과 모델 공유) | 3B 단일 모델로 의도 분류 + 보고서 통합. 원격 fallback 없음 |
| 오디오 재생 | 브라우저 `<audio>` element (HTMLAudioElement) | mp3 자장가·무궁화꽃 노래 등 — 클라이언트(로봇 UI) 측 재생, 서버 메모리 0. pygame.mixer 미사용 |
| 이미지 처리 | OpenCV | 얼굴 캡처 전처리, 품질 필터 |
| 입력 검증 | Pydantic + 정규표현식 | 등록 폼 |
| ROS2 통신 | rclpy + std .srv/.action | latched 토픽 / service / action — 브라우저 UI 는 Vite dev server `server.proxy` → Control Service REST 경유로 ROS2 명령 호출 (rosbridge / roslibjs / Nginx 미사용) |
| 거리 제어 | TF2 + 자체 PD/PID 컨트롤러 (geometry_msgs/Twist publish) | 교사 추종 거리·속도 제어. 추종 대상은 카메라 ReID (Deep SORT/OSNet) 로 식별, 거리는 RPLiDAR C1 으로 측정 (fusion) |
| 속도 제한 (사람 인접 시) | Nav2 `velocity_smoother` + 자체 사람 검출 트리거 | SR-SAF-005 |
| 품질 필터 (이미지) | OpenCV (Laplacian 블러 검사 / 히스토그램 조명·각도) | 등록 사진 캡처 |
| 지도 위젯 (브라우저) | Canvas + PGM/PNG 맵 + nav graph 좌표 오버레이 (React 컴포넌트) | SR-CAR-004 SLAM 맵 + nav graph 시각화 |
| 명령 재시도 (exponential backoff) | `tenacity` | SR-REL-005 |

## 3. ROS2 패키지 구성

vendor 패키지는 두 가지 방식으로 통합:
- **git submodule** — 깃허브 소스만 제공되는 패키지. 워크스페이스 `src/` 안에 submodule 로 추가, 우리 git 에는 외부 코드를 직접 두지 않고 commit hash 만 고정
- **apt install** — ROS distribution apt repo 에 deb 가 있는 패키지. 시스템 전역으로 설치, 워크스페이스 빌드 시간 0

1회 셋업은 README 의 단계별 명령 (`apt install` + `git submodule update --init` + `colcon build`) 을 수동 실행한다.

| 로봇 | vendor 의존성 | 통합 방식 | 자체 패키지 |
| --- | --- | --- | --- |
| GogoPing | `vicpinky_bringup` / `_description` / `_navigation` (모터 드라이버·RPLiDAR·SLAM·Nav2, pinklab-art/vic_pinky) | git submodule (`device/gogoping_ws/src/vic_pinky`, v1.0.0) | `gogoping_*` — 모드·운반·놀이·자연 촬영 등 응용 노드 |
| EduPing | OpenArm SDK | TBD — 출처/통합 방식 정보 보완 후 채움 | `eduping_*` — 모드·등하원·놀이·정리정돈·자연 촬영 등 응용 노드. 환영·작별 trajectory 는 OpenArm 으로 재생 |
| NoriArm | `open_manipulator` (ROBOTIS — robotis-git/open_manipulator) | git submodule (`device/noriarm/src/open_manipulator`) | `noriarm_*` — 블럭쌓기·정리 응용 노드 |
