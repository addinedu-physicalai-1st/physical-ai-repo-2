# pingdergarten

유치원 교육보조로봇 서비스. 아이와 놀아주고 교사를 보조한다.

- **EduPing** — 등하원·율동 안내·가게놀이·정리정돈·무궁화꽃이 피었습니다
- **GogoPing** — 교사 보조 (추종·운반)·숨바꼭질·자장가
- **NoriArm** — 블럭쌓기·정리

Addinedu 4기 최종 프로젝트 | 팀 사랑의 에듀핑 | 2026-04-23 ~ 2026-06-04

---

## 서비스 구성

| 디렉터리 | 역할 |
|---|---|
| `server/ai` | AI Hub — 음성 명령 의도 분류 (Ollama Qwen3) |
| `server/control` | Control Service — REST/WS 게이트웨이, ROS2 브리지 |
| `ui/robot-ui` | 교사용 웹 UI (Vue 3) |

## 시작하기

### 사전 준비

- Python 3.12 가상환경
- [Ollama](https://ollama.com) 설치 및 실행 (`ollama serve`)
- tmux

### 설치

```bash
# 1. 저장소 클론 (submodule 포함)
git clone --recurse-submodules <repo-url> pingdergarten
cd pingdergarten

# 또는 이미 클론했다면 submodule 초기화
git submodule update --init --recursive
```

submodule 업데이트:
```bash
git submodule update --remote  # 최신 버전으로 업데이트
git submodule foreach git pull  # 각 submodule의 최신 커밋 가져오기
```

의존성은 본인의 Python 환경에 맞게 설치한다.

```bash
pip install -e .
```

### 서버 실행 & 종료

```bash
# postgres + AI Hub + Control Service + pgweb 동시 실행 (tmux 세션)
scripts/run_server.sh

# 서비스 상태 확인
scripts/run_server.sh status

# tmux 세션 종료 (postgres/pgweb는 유지)
scripts/run_server.sh down
```

PostgreSQL + pgweb 컨테이너 완전 종료:

```bash
scripts/stop_server.sh
```

### UI 실행

**Robot UI** (로봇 인터페이스 — eduping/gogoping/noriarm 중 선택)
```bash
scripts/ui-robot.sh eduping      # 또는 gogoping / noriarm
# http://localhost:5173/
```

**Portal UI** (학부모·교사 웹앱)
```bash
scripts/ui-portal.sh
# http://localhost:5174/ — Control Service(8000)와 통신
```

**Admin UI** (관리자 데스크톱 앱)
```bash
scripts/ui-admin.sh
# PyQt5 GUI (macOS/Linux 지원)
```

## 환경 변수

루트에 `.env` 파일을 만든다 (`.env.example` 참고).
