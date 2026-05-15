---
confluence_page_id: "48332818"
confluence_url: "https://woolimi.atlassian.net/wiki/spaces/FN/pages/48332818/Implementation+Plan"
title: "Implementation Plan"
confluence_version: 8
last_synced: "2026-05-13T14:08:22"
---

# 구현 계획 (Implementation Plan)

## 0. UI 구성

| UI | 프레임워크 | 역할 |
| --- | --- | --- |
| Robot UI (EduPing·GogoPing·NoriArm 공유) | Vue 3 + Vite dev server (Chromium kiosk) + Pinia + Web Speech API (STT/TTS), 단일 코드베이스 — 각 로봇 노트북에서 `VITE_ROBOT=eduping/gogoping/noriarm` env 로 분기 인스턴스 실행, `server.proxy` 로 `/api/*` → Control Service REST (rosbridge·roslibjs·Nginx 미사용) | 공통 composables/components (호출어·STT·TTS·표정·모드 셀렉터·자연어 디스패처). 로봇별 모드 화면은 `defineAsyncComponent` 로 lazy load. 모드 매트릭스는 §0.2. 자연 촬영은 ROS2 노드가 단독 처리 (SR-PHOTO-001) |
| Admin UI | PyQt5 데스크톱 앱 (Python 3.11 + PyQt5 + requests + websocket-client). Control Service REST 경유 (`requests.Session()` cookie jar 로 fastapi-users 세션 쿠키 유지) + WebSocket `/ws/robot-state` 로 로봇 상태 push 수신. ROS2 직접 통신 안 함 | 로봇 관제 — 위치·배터리·모드·작업 상태 실시간 모니터링 (SR-ADM-001), 보조 모드 UI 제어 (추종 대상 확정·정지·지도 기반 목적지 지정·도착 알림, SR-ADM-002~005) |
| Portal Web | Vue 3 + Vite dev server (학부모·교사 공용 웹앱) + Pinia, `server.proxy` 로 `/api/*` → Control Service (사진 binary 는 Control Server 의 FastAPI StaticFiles `/api/photos-static/*` 를 같은 proxy 로 GET) | 교사 기능 (아동·학부모 등록, 출결 보드, 정보·보고서 보기), 학부모 기능 (로그인·등·하원·메뉴·사진·보고서 조회). 학부모·교사 모바일/PC 에서 같은 Wi-Fi LAN IP 로 접근 |

## 0.1 로봇 UI 모드

| 로봇 UI | 모드 |
| --- | --- |
| EduPing UI | 대기, 등원, 하원, 율동, 무궁화꽃이 피었습니다 |
| GogoPing UI | 대기, 보조, 숨바꼭질, 자장가 |
| NoriArm UI | 대기, 블럭쌓기, OX 퀴즈, 가게놀이 |

## 0.2 모드별 동작 매트릭스

| 로봇 UI | 모드 | 호출어 | 표정 | 자연 촬영 | 인접 정지 | default 표정 |
| --- | --- | :---: | :---: | :---: | :---: | --- |
| EduPing UI | 대기 | ✓ | ✓ | ✗ | ✗ | basic |
| EduPing UI | 등원 | ✓ | ✓ | ✗ | ✓ | hello |
| EduPing UI | 하원 | ✓ | ✓ | ✗ | ✓ | hello |
| EduPing UI | 율동 | ✓ | ✓ | ✓ | ✓ | fun |
| EduPing UI | 무궁화꽃이 피었습니다 | ✓ | ✓ | ✓ | ✓ | fun |
| GogoPing UI | 대기 | ✓ | ✓ | ✗ | ✗ | basic |
| GogoPing UI | 보조 | ✓ | ✓ | ✗ | ✓ | basic |
| GogoPing UI | 숨바꼭질 | ✓ | ✓ | ✓ | ✓ | fun |
| GogoPing UI | 자장가 | ✓ | ✓ | ✗ | ✗ | sleep |
| NoriArm UI | 대기 | ✓ | ✓ | ✗ | ✗ | basic |
| NoriArm UI | 블럭쌓기 | ✓ | ✓ | ✓ | ✓ | interest |
| NoriArm UI | OX 퀴즈 | ✓ | ✓ | ✓ | ✓ | fun |
| NoriArm UI | 가게놀이 | ✓ | ✓ | ✓ | ✗ | fun |

## 0.3 표정 자원

| 자원 | 종류 |
| --- | --- |
| three.js 셰이더 표정 (`ui/robot-ui/src/common/ShaderFace.vue`) | basic / hello / happy / fun / interest / bored / sad / angry / sleep — 눈·눈썹·입 파라미터 (closure / smileBow / smileThickness 등) 로 표정을 코드로 합성. 외부 이미지 자원 없음 |

## 0.4 디바이스 점유

| 디바이스 | 점유 주체 | 비고 |
| --- | --- | --- |
| 노트북 마이크 | 브라우저 (Web Speech API STT 항상 듣기 모드) | 호출어·자연어 명령 캡처. ROS2 노드 미사용 (디바이스 동시 점유 충돌 회피). 별도 wake word 모델 없이 STT 텍스트 매칭으로 호출어 검출 |
| 노트북 스피커 | 브라우저 (`speechSynthesis` + `<audio>`) | 음성 합성 + mp3 자장가·무궁화꽃 노래·환영/작별 멘트 |
| 노트북 웹캠 | ROS2 노드 (`cv_camera` 등) | 얼굴 인식·객체 인식·사람 추적·자세 인식·감정 인식·자연 촬영. ROS2 토픽으로 프레임 발행, 같은 호스트 노드들이 공유 (DDS shared memory / loopback) |
| Top Camera | ROS2 노드 | EduPing/NoriArm Top 카메라 — 객체 인식·자세 인식 |
| Gripper Camera | ROS2 노드 | 픽업 직전 정밀 검증 |
| 등록 카메라 | 브라우저 (WebRTC, Portal UI) | 등록 화면에서 웹캠을 임시 점유 (운영 시간 외) 또는 별도 USB 카메라 |

## 1. EduPing UI (Robot UI 코드베이스의 `VITE_ROBOT=eduping` 인스턴스, OpenArm + Laptop)

### 1.1 율동 안내

> 구현 완료 — [implemented.md](implemented.md) 참조

### 1.4 무궁화꽃이 피었습니다

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-PLAY-004 | 무궁화꽃이 피었습니다 | EduPing UI 가 무궁화꽃 모드에 진입해 참가 아이 (최대 5명) 를 확정하고, 아래 단계 머신으로 게임을 진행한다. 외부인·등록된 비참가 아이는 모든 단계에서 무시한다. | High |

#### 단계 머신

| 단계 | 트리거 | 동작 | 표정 | 다음 단계 |
| --- | --- | --- | --- | --- |
| 진입 | §8.2 명령 인터페이스의 모드 전환 | EduPing Top Camera + 얼굴 인식 으로 등록 임베딩 매칭, 참가 아이 (최대 5명, 시야 내 등록된 아이) 확정. ByteTrack 의 `track_id ↔ child_id` 매핑 저장. 미등록 얼굴(외부인)·등록됐지만 비참가인 아이는 매핑 제외 | hello | 준비 |
| 준비 | 참가 아이 모두 일정 거리 이상 후방 위치 | 거리 미달 시 음성 안내 | basic | 노래 |
| 노래 | 준비 완료 | EduPing UI (브라우저 `<audio>`) 가 "무궁화꽃이 피었습니다" 사전 녹음 mp3 (재생속도 랜덤) 재생 + OpenArm 양팔 눈 가리기 모션 (룰베이스) | fun | 관찰 |
| 관찰 | mp3 재생 종료 | 2~5초 랜덤 동안 EduPing Top Camera + 다중 인물 자세 인식 (YOLOv8-Pose-n) + ByteTrack 으로 진입 단계 매핑된 `track_id` 의 관절 움직임을 병렬 검출, 임계 초과 아이를 탈락 처리. 매핑 외 `track_id` (외부인·비참가 아이) 는 판정 대상에서 제외. `track_id` 가 occlusion 등으로 끊기면 face match 로 재매칭 (등록 + 참가 확정 child_id 만 매핑 복원) | interest | (탈락자 있음) 탈락 대기 / (없음) 노래 |
| 탈락 대기 | 탈락자 결정 | 탈락자가 시야 밖으로 나갈 때까지 대기 | sad | 노래 |
| 종료 (전역 트리거) | 어느 단계에서든 EduPing UI 터치 버튼 클릭 또는 호출어 + 자연어 모드 전환 명령 (mp3 재생 중이면 즉시 정지) | 게임 종료 음성 재생, 대기 모드로 전환 | happy | 대기 |

### 1.5 등원

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-IN-001 | 얼굴 캡처 | EduPing 이 정문에 상주한 상태에서 등원 모드 진입 시, 노트북 웹캠 시야에 등록된 얼굴 등장 시 단일 프레임을 캡처한다. 미등록 얼굴은 무시한다. | High |
| SR-IN-002 | 얼굴 식별 | EduPing 이 얼굴 인식 으로 등록 임베딩과 매칭해 등원하는 아이의 child_id 를 확정한다. 당일 이미 등원 기록이 있는 child_id 는 무시한다. | High |
| SR-IN-003 | 환영 인사 출력 | EduPing 이 음성 합성 으로 이름을 포함한 환영 멘트를 합성해 노트북 스피커로 재생한다. 멘트 재생 중 다른 아이가 등장하면 큐에 적재해 순차 처리한다. | High |
| SR-IN-004 | 환영 모션 | EduPing 의 OpenArm 이 사전 녹화 환영 trajectory 를 재생하고, 완료 후 출결 시각 기록 (SR-IN-006) 을 트리거한다. | High |

### 1.6 하원

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-OUT-001 | 얼굴 캡처 | EduPing 이 정문에 상주한 상태에서 하원 모드 진입 시, 노트북 웹캠 시야에 등록된 얼굴 등장 시 단일 프레임을 캡처한다. 미등록 얼굴(학부모 포함)은 무시한다. | High |
| SR-OUT-002 | 얼굴 식별 | EduPing 이 얼굴 인식 으로 등록 임베딩과 매칭해 하원하는 아이의 child_id 를 확정한다. 당일 이미 하원 기록이 있는 child_id 는 무시한다. | High |
| SR-OUT-003 | 작별 인사 출력 | EduPing 이 음성 합성 으로 이름을 포함한 작별 멘트를 합성해 노트북 스피커로 재생한다. 멘트 재생 중 다른 아이가 등장하면 큐에 적재해 순차 처리한다. | High |
| SR-OUT-004 | 작별 모션 | EduPing 의 OpenArm 이 사전 녹화 작별 trajectory 를 재생하고, 완료 후 출결 시각 기록 (SR-OUT-006) 을 트리거한다. | High |

## 2. GogoPing UI (Robot UI 코드베이스의 `VITE_ROBOT=gogoping` 인스턴스, VicPinky + Laptop)

### 2.1 보조

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-CAR-001 | 추종 대상 확인 | Admin UI "추종 시작" 버튼이 눌리면 GogoPing 노트북 디스플레이 + 음성 합성 으로 얼굴 보여달라는 안내를 출력, 노트북 웹캠으로 캡처 후 얼굴 인식 으로 등록 교사와 매칭, 디스플레이 + 음성 합성 으로 확인 멘트 ("○○선생님 맞아요?") 와 UI 확인 버튼 ("맞음" / "다시") 을 표시한 뒤 클릭으로 추종 대상을 확정한다. 매칭 실패 시 "얼굴이 잘 안 보여요. 다시 보여주세요" 안내 후 재캡처 (3회 한도). 3회 실패 시 추종 대상 확정을 취소하고 대기 상태로 복귀한다. | High |
| SR-CAR-002 | 교사 추종 | GogoPing 이 노트북 웹캠 + 사람 추적 (Deep SORT/OSNet ReID) 으로 추종 대상 1인의 방위를 잠그고, RPLiDAR C1 으로 그 방위의 거리를 측정해 거리 제어 로 따라간다. LiDAR 임계 거리 이하 진입 시 즉시 정지 (SR-SAF-006). | High |
| SR-CAR-003 | 정지·대기 입력 | Admin UI "정지" 버튼 또는 호출어 후속 정지 의도 음성 명령이 진행 중인 동작(추종/자율 주행 등)을 중단하고 대기 상태로 전이시킨다. | High |
| SR-CAR-004 | 운반 요청 수신 | Admin UI 가 SLAM 맵 + nav graph named pose 를 시각화한 지도 위젯을 표시하고, 교사가 맵 위에서 목적지를 클릭하면 named pose 를 Control Server REST 로 전달해 Control Server 가 ROS2 /carry/deliver 액션 send_goal 을 보낸다. | High |
| SR-CAR-005 | 자율 주행 | GogoPing 이 RPLiDAR C1 + 자율 주행 으로 사전 SLAM 맵·nav graph 위에서 지정 목적지까지 이동한다. | High |
| SR-CAR-006 | 도착 알림 | ROS2 액션 결과 콜백이 GogoPing 노트북 스피커 음성 합성 으로 도착을 알린다. Admin UI 는 SR-ADM-001 로봇 상태 위젯 갱신 + SR-ADM-005 도착 알림으로 인지한다. | High |
| SR-CAR-007 | 운반 후 대기 | GogoPing 이 운반 액션 완료 후 그 자리에서 대기 상태로 전이한다. | Low |
| SR-CAR-008 | LiDAR 스캔 관제 표출 | Admin UI 가 control server WS `/teleop/state` 로부터 `/gogoping/scan` 폴라 데이터 (≥360 pts, EMA Hz, age_ms) 를 수신해 GogoPing 대시보드 4분면 중 한 칸을 차지하는 풀사이즈 폴라 뷰로 표출한다. 헤더 LiDAR chip 은 실측 Hz 로 갱신, age > 500ms 면 "신호 지연" 으로 표시. 4방향 (앞/뒤/좌/우 ±15°) 거리 통계 십자 배치. 좌표 변환은 ROS REP 103 → Qt top-down (전방 = 화면 위). | Medium |
| SR-SAF-006 | 추종 거리 유지 | GogoPing 이 RPLiDAR C1 으로 카메라 ReID 가 잠근 방위의 거리를 측정해 거리 변동에 따라 속도·정지를 결정한다. 카메라는 추종 대상 식별, LiDAR 는 거리 측정으로 책임 분담. | High |

#### 단계 머신

| 단계 | 트리거 | 동작 | 표정 | 다음 단계 |
| --- | --- | --- | --- | --- |
| 대기 | 보조 모드 진입 또는 Admin UI "정지" 클릭 | 그 자리 대기 | basic | 추종 대상 확인 / 운반 중 |
| 추종 대상 확인 | Admin UI "추종 시작" 클릭 | SR-CAR-001 절차 (얼굴 보여달라 안내 → 캡처 → 매칭 → 확인 멘트 → UI 확인 버튼 클릭, 매칭 실패 시 3회 한도 재캡처) | interest | (확정) 추종 / (거부) 대기 / (3회 매칭 실패) 대기 |
| 추종 | 추종 대상 확정 | 노트북 웹캠 + 사람 추적 + 거리 제어 로 교사 추종 | happy | 대기 (Admin UI "정지" 클릭) / Searching (시야 로스트) |
| Searching | 추종 대상 매칭 실패 또는 추종 중 시야 로스트 | 회전·이동·음성 호출 ("선생님?") 로 대상 재탐색 | interest | (재발견) 추종 / (타임아웃) 대기 |
| 운반 중 | Admin UI 목적지 선택 | 자율 주행 으로 nav graph 목적지로 이동 | interest | 도착 |
| 도착 | 자율 주행 액션 완료 | 대기 상태로 전이 후 교사앱 토스트·사운드 + GogoPing 노트북 스피커 음성 알림 | happy | 대기 |
| 정지 (전역 트리거) | 어느 단계에서든 UI "정지" 버튼 클릭 또는 호출어 + 정지 의도 발화 (호출어만 부르면 일시 정지 + 대답 후 직전 단계 재개) | 진행 동작 종료 → 대기 | basic | 대기 |

### 2.2 숨바꼭질

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-PLAY-007 | 숨바꼭질 | GogoPing 이 숨바꼭질 모드에 진입해 참가 아이를 확정하고, 아래 단계 머신으로 게임을 진행한다. | High |

#### 단계 머신

| 단계 | 트리거 | 동작 | 표정 | 다음 단계 |
| --- | --- | --- | --- | --- |
| 진입 | §8.2 명령 인터페이스의 모드 전환 | 모드 진입 | hello | 위치 이동 |
| 위치 이동 | 진입 직후 | 자율 주행 으로 놀이 위치 (`play_area`) 로 이동 | basic | 참가자 확정 |
| 참가자 확정 | 놀이 위치 도착 | GogoPing 노트북 웹캠 + 얼굴 인식 으로 등록 임베딩과 매칭해 참가 아이 (최대 5명, 시야 내 등록된 아이) 를 확정 | hello | 카운트다운 |
| 카운트다운 | 참가자 확정 | GogoPing 노트북 디스플레이의 셰이더 로봇 눈 (눈 가리기 표정) + 음성 합성 으로 30초 카운트다운 | fun | 순찰 |
| 순찰 | 카운트다운 종료 | 자율 주행 으로 무작위 `patrol_*` named pose 순찰 | interest | 호명 (참가 아이 발견 시) |
| 호명 | 시야 내 등록 참가 아이 발견 (얼굴 인식) | 음성 합성 으로 이름 호명, 해당 아이를 "잡힘" 으로 게임에서 제외 | happy | (남은 아이) 순찰 / (모두 잡힘) 종료 |
| 종료 (전역 트리거) | 모든 참가 아이 발견 / 타임아웃 / 교사 종료 명령 (호출어 + 자연어 / UI) | 종료 음성 재생, 대기 모드로 전환 | (모두 발견) happy / (타임아웃) sad / (교사 종료) basic | 대기 |

### 2.3 자장가

> 구현 완료 — [implemented.md](implemented.md) 참조

### 2.4 낮잠 시각 기록

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-NAP-002 | 낮잠 시각 기록 | GogoPing 이 낮잠 모드(자장가) 진입·종료 시각을 Control Server REST 로 전달하고, Control Server 가 DB `mode_history` 에 기록한다. AI Server 보고서 생성(SR-RPT-001) 시 해당 당일 낮잠 시작·종료 시각을 조회해 요약에 포함한다. | High |

### 2.5 주행 안전 / 자가관리

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-SAF-001 | 사람·장애물 감지 | GogoPing 이 RPLiDAR C1 occupancy + 노트북 웹캠 + 객체 인식 으로 주변 사람·장애물을 모든 모드에서 항상 감지한다. | High |
| SR-SAF-002 | 충돌 회피 | GogoPing 이 자율 주행 의 동적 장애물 회피 로 주행 중 동적 장애물을 회피한다. 모든 모드에서 항상 활성. | High |
| SR-SAF-005 | 사람 근접 시 감속 | GogoPing 이 자율 주행 의 속도 제한 으로 사람 인접 거리에 따라 최대 속도를 스케일 다운한다. 모든 모드에서 항상 활성. | Low |
| SR-REL-004 | 배터리 저하 복귀 | GogoPing 이 배터리 임계치 도달 시 비긴급 작업(추종 제외 모든 상태)을 cancel 하고 자율 주행 으로 충전소 (`charger`) 로 복귀한다. | Low |

### 2.6 nav graph named pose 카탈로그

| key | 위치 | 사용 SR |
| --- | --- | --- |
| play_area | 숨바꼭질 놀이 위치 | SR-PLAY-007 |
| patrol_1 .. patrol_N | 순찰용 무작위 위치 (N ≥ 3 권장) | SR-PLAY-007 |
| charger | 충전소 | SR-REL-004 |

> 위 카탈로그는 시스템이 사전 의존하는 named pose 키 집합이다. SR-CAR-004 운반 목적지는 교사가 맵에서 동적으로 선택하므로 카탈로그 외이며, 사전 키가 아니라도 nav_graph 에 등록된 임의 named pose 또는 좌표면 된다.

### 2.7 카메라 영상 스트리밍

> 구현 완료 — [implemented.md](implemented.md) 참조

## 3. NoriArm UI (Robot UI 코드베이스의 `VITE_ROBOT=noriarm` 인스턴스, 교실 OMX)

### 3.1 블럭쌓기

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-PLAY-003 | 블럭쌓기 | NoriArm 이 블럭쌓기 모드에 진입해 참가 아이 1명과 블럭 5개를 번갈아 쌓는 협동 놀이를 아래 단계 머신으로 진행한다. | High |

#### 단계 머신

| 단계 | 트리거 | 동작 | 표정 | 다음 단계 |
| --- | --- | --- | --- | --- |
| 진입 | §8.2 명령 인터페이스의 모드 전환 | 모드 진입 | hello | 참가자 확정 |
| 참가자 확정 | 진입 직후 | NoriArm 노트북 웹캠 + 얼굴 인식 으로 참가 아이 1명 확정 | hello | 시작 안내 |
| 시작 안내 | 참가자 확정 | 음성 합성 으로 시작 안내 ("같이 쌓아볼까?"), 5개 출발 위치(ROI)에 블럭 5개를 1:1 매핑으로 사전 배치 — 사람 색 3개 (사람 ROI 3개) + 로봇 색 2개 (로봇 ROI 2개) | interest | 진행 |
| 진행 | 시작 안내 또는 출발 위치에 변화 | NoriArm Top 카메라 + 객체 인식 으로 5개 출발 위치 ROI 모니터링, 로봇 ROI 2개 중 자기 색 블럭이 남아있으면 모방학습 정책 (블럭쌓기 ACT) 으로 1개 집어 쌓고 (그리퍼 카메라로 픽업 직전 정밀 검증) 홈 복귀, 로봇 ROI 가 모두 비고 사람 ROI 만 남은 상태에서는 사람 차례로 대기 | interest | (5개 ROI 모두 빔) 종료 |
| 종료 (전역 트리거) | 5개 출발 위치 ROI 모두 빔 또는 호출어 + 자연어 종료 명령 또는 UI 종료 | 축하 음성 합성 + 대기 모드로 전환 | happy | 대기 |

### 3.3 게임 프레임워크 (NoriArm 공통)

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-NORI-001 | 게임 매니페스트 | NoriArm 의 각 게임이 하드웨어 요구 (카메라 id·역할·해상도·sim/real 디바이스 매핑 / OMX 팔 id·model·ROS namespace·sim 백엔드(gazebo)·real 백엔드(dynamixel 포트)) 와 정책 종류 (`rule_based` / `smolvla`) 를 YAML 매니페스트 (`device/noriarm_ws/src/noriarm_framework/games/<name>/game.yaml`) 로 선언한다. 런타임은 매니페스트 기반으로 게임을 동적으로 구성하며, 한 게임에 필요한 카메라·팔의 종류와 갯수가 게임마다 다를 수 있다. | High |
| SR-NORI-002 | 정책 인터페이스 | 게임 진행 로직을 `Policy` Protocol (`reset(ctx)`, `step(observation) -> action`) 로 추상화해 rule-based 와 smolVLA 모방학습 추론을 같은 게임 루프 코드 위에서 교체 가능하게 한다. `Observation` 은 카메라 이미지·검출된 손 위치·로봇 관절 상태·언어 프롬프트 등 optional 필드를 갖는 dataclass, `Action` 은 idle / replay_trajectory(name) / joint_targets(values) 의 union 으로 표현한다. | High |
| SR-NORI-003 | 런처 CLI | `python -m noriarm_framework run --game <name> --target sim\|real` 진입점이 매니페스트를 읽어 ROS2 launch description 을 합성하고, 정책 인스턴스를 동적 import 한 뒤 게임 루프를 시작한다. `validate` (매니페스트 + 하드웨어 가용성 검증) / `list` (등록된 게임 목록) 서브커맨드를 함께 제공한다. | High |
| SR-NORI-004 | 하드웨어 가용성 검증 | 게임 시작 전 매니페스트가 요구하는 카메라(`v4l2-ctl --list-devices`) 와 OMX 팔(`ros2 node list` + 매니페스트의 namespace) 가용성을 점검해 부재 시 명시적으로 실패한다. sim 타깃에서는 sim 디바이스 (Gazebo · 가상 카메라) 기준으로 검증한다. | Medium |
| SR-NORI-005 | 동적 launch 생성 | 매니페스트의 `cameras` / `arms` / `target` 조합으로 ROS2 launch description 을 동적 합성한다 (real → ros2_control + USB 카메라 노드 / sim → Gazebo + 가상 카메라). 네트워크 토픽 이름은 sim/real 동일하게 유지해 정책·UI 코드는 어느 쪽에서 도는지 모르도록 한다. | Medium |
| SR-NORI-006 | 타깃 자동 감지 | Control Server `GET /api/noriarm/health` 가 `/dev/omx_follower` 존재 여부 + Dynamixel SDK ping + `ros2 node list` 의 실물 드라이버 노드 상태로 실물 가용성을 판정해 `{real_arm_present, active_target, gazebo_running, controller_active}` 를 반환한다. NoriArm UI 가 마운트 시 호출해 상단 배지 (실물/시뮬) 와 디폴트 target 을 결정한다. 디폴트 규칙: real_arm_present=true 면 real, 아니면 sim. | Medium |
| SR-NORI-007 | 세션 라이프사이클 | Control Server `POST /api/noriarm/session { target }` / `DELETE /api/noriarm/session` 가 매니페스트의 `arm.sim.backend` 에 따라 분기한다. `joint_state_only` 면 `/joint_states` 를 SSE 로 forward 만 하고 ROS 자식 프로세스 spawn 은 없음 (OX 퀴즈 등 경량 시각화 게임용). `gazebo` 면 `omx_f_gazebo.launch.py` 등 launch 파일을 spawn (블럭쌓기 등 물리 시뮬 필요 게임용). 진행 상태는 SSE `/api/noriarm/session/events` 로 `{phase: "launching" → "ready" → "running" → "terminating"}` push. real 타깃은 launch 생략. 개발 환경에서 Control Server 가 노트북 셸에서 직접 실행되므로 DISPLAY 등은 자연 상속. | Medium |
| SR-NORI-008 | 수동 target override | NoriArm UI 의 토글 (자동 감지 결과 옆) 이 강제로 target=sim 또는 target=real 을 지정해 SR-NORI-007 세션 시작 페이로드에 반영. 실물 미연결 상태에서 real 선택 시 명확한 에러 (실물 연결 안내) 를 반환하고 세션을 시작하지 않는다. | Low |

### 3.4 OX 퀴즈

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-PLAY-010 | OX 퀴즈 진행 | NoriArm UI 가 OX 퀴즈 모드에 진입해 `shared/ox_quiz.json` 에서 3문제를 무작위 추출, 각 문제마다 5초 카운트다운 후 정답을 공개하고, NoriArm 게임 프레임워크 (§3.3) 의 OX 퀴즈 게임 (overhead 카메라 1대 + OMX 팔 1대 매니페스트 + rule_based 정책) 으로 정답 trajectory 를 재생한다. 3문제가 끝나면 종료 화면을 표시한다. | High |
| SR-PLAY-011 | OX 퀴즈 — 손 터치 검출 | overhead 카메라 + 손 검출 (mediapipe Hands) 으로 아이가 O 또는 X 영역 위에 손을 올린 시점을 검출해 정답 여부를 판정하고 점수를 누적한다. 검출 이벤트는 게임 세션 WebSocket 으로 NoriArm UI 에 실시간 push 한다. **sim/real 모두 동일한 vision 파이프라인을 노트북 웹캠에 돌리고, sim/real 차이는 OMX 팔 레이어 (joint_state_only vs Dynamixel) 에만 국한** — 팀장 노트북 한 대로 책상에 O/X 영역 두 개를 종이로 표시해두고 회귀 테스트한다. ROI 보정은 캘리브레이션 단계로 분리. | Medium |
| SR-PLAY-012 | OX 퀴즈 — smolVLA 정책 | rule_based 대신 smolVLA 모방학습 추론으로 답을 가리키는 trajectory 를 생성하는 대안 정책을 추가한다. 매니페스트의 `policy.kind` 만 `smolvla` 로 바꾸면 동일 게임 루프 / UI 가 ML 정책으로 동작. | Low |
| SR-PLAY-013 | OX 퀴즈 세션 API | Control Server REST 가 `POST /api/noriarm/games/ox-quiz/sessions` 로 게임 세션을 시작하고, `POST /api/noriarm/games/ox-quiz/sessions/{id}/answer` 로 정답을 받으면 §3.3 게임 프레임워크의 룰 정책을 호출해 trajectory publish 를 트리거한다. 게임 이벤트(다음 문제·손 검출·정답·점수·종료)는 SSE `/api/noriarm/games/ox-quiz/sessions/{id}/events` 로 NoriArm UI 에 push, 로봇팔 관절값은 SSE `/api/noriarm/joint-states/stream` 으로 별도 push (three.js URDF 뷰어용). rosbridge_websocket / roslibjs 는 사용하지 않는다 — Control Server 가 직접 다리. | Medium |

### 3.5 가게놀이

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-PLAY-009 | 가게놀이 | NoriArm 이 가게놀이 모드에 진입해 아이의 음성 모형 요청을 받아 OMX 팔로 모형을 집어 아이에게 건네는 놀이를 아래 단계 머신으로 진행한다. NoriArm 게임 프레임워크 (§3.3) 의 매니페스트로 OMX 팔 1대 + Top 카메라 + Gripper 카메라 + Policy (rule_based / smolvla) 를 구성한다. | High |

#### 단계 머신

| 단계 | 트리거 | 동작 | 표정 | 다음 단계 |
| --- | --- | --- | --- | --- |
| 진입 | §8.2 명령 인터페이스의 모드 전환 | 모드 진입, 모형 3종 (사과 / 우유팩 / 아이스크림콘) 사전 배치 ROI 검증 | hello | 요청 대기 |
| 요청 대기 | 진입 직후 또는 전달 완료 | 음성 합성 으로 안내 ("뭐 줄까?"). 호출어 후속 발화 대기 | basic | 요청 수신 |
| 요청 수신 | 호출어 + 후속 발화 | 노트북 마이크 + 음성 인식 → 의도 분류 LLM 으로 모형 3종 중 하나 선택 (의도 불분명 시 음성 합성 으로 재요청) | interest | 픽업 |
| 픽업 | 모형 선택 확정 | NoriArm Top 카메라 + 객체 인식 으로 선택 모형의 위치를 검출, Policy 가 OMX 팔로 픽업 trajectory 를 생성 (그리퍼 카메라로 픽업 직전 정밀 검증) | interest | 전달 |
| 전달 | 픽업 완료 | 음성 합성 으로 안내 ("여기 있어"), OMX 팔이 아이 측 ROI 로 모형을 옮겨 release. 사람이 받아간 것을 ROI 비어있음 으로 검출 | happy | (남은 모형) 요청 대기 / (모두 빔) 종료 |
| 종료 (전역 트리거) | 모든 모형 소진 또는 호출어 + 자연어 종료 명령 또는 UI 종료 | 종료 음성 재생, 대기 모드로 전환 | happy | 대기 |

## 4. Admin UI (PyQt5 데스크톱 앱, 로봇 관제)

### 4.1 로봇 상태 모니터링

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-ADM-001 | 로봇 상태 표시 | Admin UI(PyQt5)가 Control Server WebSocket 채널 `/ws/robot-state` 를 `websocket-client` 라이브러리로 구독해 로봇별 상태 위젯 (위치·배터리·현재 모드·작업·도착 이벤트) 을 실시간 갱신 표시한다. 인증은 fastapi-users 세션 쿠키를 WebSocket handshake 헤더로 전달. | High |

### 4.2 보조 모드 관제

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-ADM-002 | 추종 대상 확정 UI | Admin UI 가 "추종 시작" 버튼 클릭 시 GogoPing 에 얼굴 캡처·매칭을 요청하고, 매칭 결과를 디스플레이에 표시한 뒤 "맞음" / "다시" 클릭으로 추종 대상을 확정한다. | High |
| SR-ADM-003 | 보조 정지·재개 입력 | Admin UI 의 "정지" 버튼 클릭이 Control Server REST 로 정지 명령을 전달해 GogoPing 을 대기 상태로 전이시킨다. | High |
| SR-ADM-004 | 지도 기반 목적지 지정 | Admin UI 가 SLAM 맵 + nav graph named pose 를 시각화한 지도 위젯을 표시하고, 관리자가 목적지를 클릭하면 named pose 를 Control Server REST 로 전달해 운반 요청을 보낸다. | High |
| SR-ADM-005 | 도착 알림 수신 | Admin UI 가 SR-ADM-001 로봇 상태 위젯 갱신으로 GogoPing 목적지 도착을 인지하고 토스트 알림을 표시한다. | High |

## 5. Portal Web (학부모·교사 공용 웹앱)

### 5.1 교사 — 등록

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-REG-005 | 얼굴 이미지 캡처 | Portal Web 이 브라우저 WebRTC 로 등록 카메라에 접근해 다양 각도(정면·측면·상하 회전) 15장을 캡처하고 블러·각도·조명 품질 필터 + anti-spoofing (liveness 검증) 을 적용한다. | High |

### 5.2 교사 — 출결

> 구현 완료 — [implemented.md](implemented.md) 참조

### 5.3 교사 — 정보 보기

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-OPS-015 | 자녀 정보 보기 | Portal Web 이 Control Service REST 로 child 테이블을 조회해 자녀 기본 정보 (이름·생년월일·반·등록 사진) 를 표시한다. 등록 사진 binary 는 Control Server 가 FastAPI StaticFiles 로 마운트한 정적 경로 (`/api/photos-static/...`) 를 브라우저가 GET 한다. | Low |

### 5.4 학부모 — 로그인·계정

> 구현 완료 — [implemented.md](implemented.md) 참조

### 5.5 학부모 — 자녀 선택

> 구현 완료 — [implemented.md](implemented.md) 참조

### 5.6 학부모 — 등·하원 조회

> 구현 완료 — [implemented.md](implemented.md) 참조

### 5.7 학부모 — 메뉴

> 구현 완료 — [implemented.md](implemented.md) 참조

### 5.8 학부모 — 사진첩 조회

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-PHOTO-003 | 학부모 사진 조회 | Portal Web 이 선택된 자녀가 포함된 positive 카테고리 사진을 표시하고 사진별 다운로드를 지원한다. 이미지 binary 는 Control Server 가 FastAPI StaticFiles 로 마운트한 정적 경로 (`/api/photos-static/...`) 를 Vite dev proxy 경유로 브라우저가 GET 한다. | Low |

### 5.9 학부모 — 일과 보고서 조회

> 구현 완료 — [implemented.md](implemented.md) 참조

## 6. Control Server / DB (백엔드)

### 6.1 등록 / 인증

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-REG-006 | 얼굴 데이터 저장 | Control Server 가 등록 사진 15장에서 얼굴 인식 으로 다중 임베딩을 추출해 child_id 별로 DB BLOB 에 저장한다. 매칭 시 다중 임베딩 중 최대 유사도로 판정해 카메라가 달라도 robust 하게 인식한다. | High |
| SR-REG-010 | 얼굴 인식 anti-spoofing | 얼굴 캡처(등록·매칭 시점) 가 anti-spoofing (liveness detection) 으로 실제 얼굴 vs 사진·영상 도용을 구별한다. | High |

### 6.2 출결 기록

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-IN-006 | 등원 시각 기록 | Control Server 가 DB attendance 테이블에 child_id, time, type=IN 으로 등원 시각을 INSERT 한다. | High |
| SR-OUT-006 | 하원 시각 기록 | Control Server 가 DB attendance 테이블에 type=OUT 으로 하원 시각을 INSERT 한 후 같은 트랜잭션에서 `ai_job(kind=report)` INSERT 로 일과 보고서 생성 작업을 enqueue 한다. | High |

### 6.3 통신 인터페이스

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-COM-001 | 로봇 상태 발행 | 각 로봇 state publisher 가 1Hz ROS2 토픽 `/eduping/state` · `/gogoping/state` · `/noriarm/state` (로봇별 namespace) 로 위치·배터리·현재 작업·운반 액션 결과를 publish 하고 Control Server 가 세 토픽을 모두 구독·수집한 뒤 WebSocket 채널 `/ws/robot-state` 로 Admin UI 에 push 한다 (SR-ADM-001). | High |
| SR-COM-002 | 작업 명령 전달 | Control Server 가 ROS2 service/action 표준 인터페이스(.srv/.action) 로 각 로봇에 작업 명령을 전달한다. | High |

### 6.4 신뢰성

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-REL-002 | 작업 안전 중단 | 각 로봇 컨트롤러 상태 머신이 작업 실패 시 safe_stop 상태로 전이한다. | High |
| SR-REL-005 | 명령 재시도 | Control Server 클라이언트 래퍼가 exponential backoff 로 일시적 통신 오류 명령을 일정 횟수 재시도한다. | Low |
| SR-REL-006 | 상태 복원 | Control Server·AI Server 가 시작 시 DB 스냅샷에서 출결·모드의 마지막 상태를 로드하고, AI Server 는 `ai_job` 의 `running` 행을 `pending` 으로 일괄 reset 한다. | Low |

### 6.5 데이터 모델

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-DAT-002 | 얼굴 데이터 저장 | DB(임베딩 BLOB) · 오브젝트 스토리지(이미지 binary) · 메타 행으로 분리 저장한다. | High |
| SR-DAT-004 | 운반 작업 이력 | DB 가 carry_job(요청·적재·도착·상태) 테이블에 운반 이력을 저장한다. | Low |
| SR-DAT-005 | 작업 로그 | DB 가 task_log(시작·종료·결과·사유) 테이블에 작업 로그를 기록한다. | Low |
| SR-DAT-009 | 모드 상태 | DB 가 `mode_history(robot_id, time, mode)` + 로봇별 현재 모드 캐시로 로봇별 독립 모드 상태를 기록한다. | High |
| SR-DAT-011 | 사진첩 데이터 | 로컬 디스크 (`server/storage/photos/`, 사진 binary) · DB `photo` 테이블 (경로·촬영시각·모드·트리거 child_id·감정 점수·감정 카테고리) · DB `photo_subject(photo_id, child_id)` N:N 매핑 테이블 (사진 내 등장한 모든 등록 아이) 로 분리 저장한다. 학부모 사진첩 조회 (SR-PHOTO-003) 는 `photo_subject` 매핑으로 자녀 포함 여부를 판정한다. Control Server 가 FastAPI StaticFiles 로 마운트한 정적 경로 (`/api/photos-static/...`) 를 학부모 브라우저는 Vite dev proxy 경유, 교사앱(PyQt5)은 `requests.get(url)` 으로 직접 GET 한다. | Low |
| SR-DAT-012 | nav graph | DB 가 nav_graph 테이블에 SLAM 맵 위 nav graph (node·edge·named pose) 를 저장한다. (MVP: `shared/waypoints.yaml` + node-only — 2026-05-13 완료, DB 마이그레이션 + edge 그래프는 follow-up) | Low |
| SR-DAT-013 | 비동기 작업 큐 데이터 | DB 가 ai_job(id·kind·payload·status·attempts·max_attempts·last_error·created_at·started_at·finished_at) 테이블에 §7.3 비동기 작업 큐 행을 저장한다. status 는 pending/running/done/failed 상태 머신을 가지며 worker 픽업은 `FOR UPDATE SKIP LOCKED` 로 race-safe 처리한다. | High |

## 7. AI Server (Vision + LLM)

### 7.1 사진 분류 / 저장

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-PHOTO-002 | 아이 식별·사진첩 업로드 | AI Server worker 가 `ai_job(kind=photo_classify)` 큐에서 작업을 픽업해 해당 사진을 얼굴 인식 으로 프레임 내 모든 등록 아이를 식별하고 `photo_subject(photo_id, child_id)` N:N 매핑 테이블에 INSERT 한다. 트리거된 1명 (감정 임계 초과 주체) 은 캡처 시점 메타의 트리거 child_id 로 별도 보존한다. | Low |

### 7.2 일과 보고서 생성

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-RPT-001 | 일과 보고서 생성 | AI Server worker 가 `ai_job(kind=report)` 큐에서 작업을 픽업해 해당 child_id 의 하루치 사진 메타데이터 (SR-PHOTO-004 의 시각·감정 카테고리·모드·트리거 child_id) · 모드 이력 (SR-DAT-009 mode_history, 낮잠 시작·종료 시각 포함) · 당일 점심메뉴 (SR-DAT-007 menu) 를 로컬 Ollama LLM (`server/ai/config.py` 의 `ollama_report_model`, 기본 `qwen2.5:7b` — 잡담용 `ollama_chat_model`·의도 분류용 `ollama_model` 과 별도) 으로 자연어 요약해 DB report 테이블에 저장한다. enqueue 는 SR-OUT-006 하원 시각 기록 시점에 Control Server 가 처리한다. | Low |

### 7.3 비동기 작업 큐

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-AI-001 | 비동기 작업 큐 | Control Server 가 사진 수신 시점 (SR-PHOTO-001) 과 하원 기록 시점 (SR-OUT-006) 에 `ai_job` INSERT 로 enqueue 하고, AI Server worker 프로세스가 `ai_job` 테이블 (PostgreSQL) 을 `FOR UPDATE SKIP LOCKED` 로 폴링해 §7.1 사진 분류·§7.2 보고서를 비동기 처리한다. 재시작 시 `running` 행을 `pending` 으로 일괄 reset 하며, 사진 분류·보고서 생성은 자연 멱등키 (사진 sha256, report `(child_id, date)` UNIQUE) 로 중복 실행을 흡수한다. (§7.4 음성 처리는 동기) | High |

### 7.4 음성 처리

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-VOICE-001 | 음성 입력 수신 | 각 로봇 UI (브라우저) 가 호출어 감지 신호 후 마이크 음성을 캡처해 클라이언트 측에서 텍스트로 변환한 뒤 Vite dev server `server.proxy` 를 통해 Control Service `/api/voice/intent` 에 텍스트를 전송한다. Control Service 가 AI Hub (의도 분류 LLM) 호출 후 결과에 따라 ROS2 명령을 publish 한다. | High |

## 8. 다중 UI 공통

### 8.1 로봇팔 인접 정지 (EduPing UI + GogoPing UI + NoriArm UI)

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-SAF-003 | 인접 정지 | EduPing(OpenArm)·NoriArm이 작업영역 워치독 + 카메라 사람 검출로 진입 시 trajectory 를 일시 정지한다. | High |

### 8.2 명령 인터페이스 (모든 UI — 자연어 + 클릭)

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-UI-002 | UI 모드·명령 클릭 선택 | 각 로봇 UI 가 현재 UI 가 지원하는 모드 버튼·명령 버튼을 상시 노출하고, 클릭 시 자연어 명령과 동등한 효과로 ROS2 토픽·서비스를 발행한다. | High |
| SR-OPS-001 | 모드 전환 | 호출어 후속 자연어 모드 전환 명령 또는 UI 모드 버튼 클릭이 해당 로봇의 ROS2 latched 토픽 (`/eduping/mode` · `/gogoping/mode` · `/noriarm/mode` 중 하나) 를 발행하고 그 로봇의 노드들이 자기 namespace 의 mode 토픽만 구독해 모드를 적용한다. 로봇 간 모드는 독립적이다. | High |
| SR-OPS-011 | 모드 내 자연어 명령 | 호출어 후속 자연어 명령을 의도 분류 LLM 으로 현재 모드의 서브 명령 (정지·진행·대상·목적지 등) 으로 라우팅한다. UI 클릭과 동등한 효과. | High |
| SR-OPS-013 | 보조 모드 음성 입력 제한 | GogoPing 이 보조 모드에 진입한 동안 호출어 인식 시 일시 정지 + 음성 대답하지만, 후속 명령은 정지 의도("정지" / "멈춰" 등) 만 받아 대기 상태로 전이시키고, 그 외 명령(모드 전환·목적지 등)은 무시하고 일시 정지를 해제해 직전 동작을 재개한다. 모드 전환·운반 명령 등은 교사앱 UI 클릭으로만 가능. 음성 출력(안내·도착 알림 등)은 정상. | High |

### 8.3 표정 상시 표시 (모든 로봇 UI)

> 구현 완료 — [implemented.md](implemented.md) 참조

### 8.4 사진 자연 캡처 (모든 로봇 UI, 놀이 모드 한정)

| S ID | Name | Description | Priority |
| --- | --- | --- | --- |
| SR-PHOTO-001 | 자연 촬영 | 각 로봇 자연 촬영 ROS2 노드가 §0.2 매트릭스의 자연 촬영 ✓ 모드 (놀이 모드) 동안 카메라 프레임을 구독해 감정 인식 결과가 happy/fun/interest (긍정) 또는 우울·두려움 (부정) 임계 초과 시 사진을 캡처해 Control Server 로 REST 업로드한다. Control Server 는 binary 를 로컬 디스크 (`server/storage/photos/`) 에 저장하고 `photo` 행 INSERT 후 `ai_job(kind=photo_classify)` INSERT 로 분류 작업을 enqueue 한다. UI 는 카메라를 점유하지 않는다. | Low |
| SR-PHOTO-004 | 사진 메타데이터 첨부 | 자연 촬영 ROS2 노드가 캡처 시 (시각·모드·트리거 child_id·감정 점수·감정 카테고리(positive/negative)) 메타데이터를 사진과 함께 첨부해 전송한다. 모드는 자기 로봇 namespace 의 mode 토픽 (`/<robot>/mode`) 구독 결과, 트리거 child_id 는 자노드 얼굴 인식 매칭 결과 (감정 임계 초과를 일으킨 주체 1명) 를 사용한다. 프레임 내 다른 등장 아이의 식별·매핑은 SR-PHOTO-002 에서 후처리. | Low |
| SR-PHOTO-005 | 자연 촬영 빈도 제한 | 자연 촬영 ROS2 노드가 5단(감정 임계치 / child 쿨다운 / 모드 한도 / 일일 한도 / 시각 중복 제거) throttling 을 통과한 프레임만 Control Server 로 업로드한다. | Low |
