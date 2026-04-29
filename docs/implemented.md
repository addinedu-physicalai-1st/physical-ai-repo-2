# 구현 완료 (Implemented)

이 문서는 [implementation-plan.md](implementation-plan.md) 에서 **완전히** 구현이 끝난 SR 을 옮겨 둔 곳이다. 이동 규칙은 루트 [CLAUDE.md](../CLAUDE.md) 의 "구현 완료 항목 관리" 섹션 참조.

부분 구현 (UI 만 완료, ROS2 publish 남음 등) 은 옮기지 않는다 — 모든 부분이 끝났을 때 한 번에 이동.

## 2. GogoPing UI

### 2.5 자장가

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-NAP-001 | 자장가 재생 | GogoPing UI (브라우저 `<audio>`) 가 사전 등록된 자장가 mp3 1곡을 재생한다. 종료는 §8.2 명령 인터페이스 (호출어 + 자연어 모드 전환) 로 처리. | High | `ui/robot-ui/src/composables/useModeAudio.ts`, `ui/robot-ui/public/audio/lullaby.mp3` | 2026-05-04 |

## 7. AI Server

### 7.4 음성 처리

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-VOICE-002 | 음성 인식 (STT) | 각 로봇 UI (브라우저) 가 Web Speech API (`webkitSpeechRecognition`, ko-KR) 로 음성을 텍스트로 변환한다 (클라이언트 측, 서버 STT 미사용). | High | `ui/robot-ui/src/composables/useSTT.ts` | 2026-05-04 |
| SR-VOICE-003 | 의도 분류 | AI Server 가 의도 분류 LLM 으로 텍스트의 의도(모드 전환 / 모드 내 서브 명령)를 분류한다. 분류되지 않는 발화는 무시한다. | High | `server/ai/{hub,llm}.py` (Ollama qwen2.5:3b) | 2026-05-04 |
| SR-VOICE-005 | 음성 출력 (TTS) | 각 로봇 UI (브라우저) 가 `window.speechSynthesis` API (ko-KR voice) 로 응답 텍스트를 음성으로 출력한다 (클라이언트 측, 서버 TTS 미사용). | High | `ui/robot-ui/src/composables/useTTS.ts` | 2026-05-04 |

## 8. 다중 UI 공통

### 8.2 명령 인터페이스

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-VOICE-007 | 호출어 인식 | 각 로봇 UI 가 Web Speech API STT 항상 듣기 모드로 텍스트 스트림을 모니터링하다 자기 이름 호출어("에듀핑" / "고고핑" / "노리암") 단어 매칭 시 즉시 진행 중인 동작을 일시 정지하고 음성으로 대답한 뒤 후속 명령 수신 윈도우 (5초) 를 활성화한다. 호출어와 명령이 같은 발화에 포함된 경우 (예: "에듀핑, 정리정돈 시작해") 는 호출어 직후 텍스트를 그대로 명령으로 처리하고 별도 윈도우 대기 없이 즉시 의도 분류로 전달한다. | High | `ui/robot-ui/src/composables/useVoiceController.ts` | 2026-05-04 |

### 8.3 표정 상시 표시

| S ID | Name | Description | Priority | 구현 위치 | 완료일 |
| --- | --- | --- | --- | --- | --- |
| SR-UI-001 | 표정 상시 표시 | 각 로봇 UI 가 표정 자원 (basic·hello·happy·fun·interest·bored·sad·angry — pinky_pro WebP 변환본 + sleep — 별도 자원) 을 현재 모드·이벤트에 따라 디스플레이에 상시 재생한다. | High | `ui/robot-ui/src/common/EmotionDisplay.vue`, `ui/robot-ui/public/emotions/*.webp` | 2026-05-04 |

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
