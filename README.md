# pingdergarten

유치원 교육보조로봇 서비스. 아이와 놀아주고 교사를 보조한다.

- **EduPing** — 등하원·율동 안내·가게놀이·정리정돈·무궁화꽃이 피었습니다
- **GogoPing** — 교사 보조 (추종·운반)·숨바꼭질·자장가
- **NoriArm** — 블럭쌓기·정리

Addinedu 최종 프로젝트 | 팀 사랑의 에듀핑 | 2026-04-23 ~ 2026-06-04

---

## 서비스 구성

| 디렉터리 | 역할 |
|---|---|
| `server/ai` | AI Hub — 음성 명령 의도 분류 (Ollama Qwen2.5 / Gemma3 / bge-m3) |
| `server/control` | Control Service — REST/WS 게이트웨이, ROS2 브리지 |
| `ui/robot-ui` | 교사용 웹 UI (Vue 3) |

## 시작하기

### 사전 준비

호스트에 다음이 설치되어 있어야 한다:

- **conda** (miniforge / miniconda / anaconda) — Python 환경 관리
- **Docker + Docker Compose** — postgres / pgweb 컨테이너 (`scripts/run_server.sh` 가 의존)
- **Node.js 18+ / npm** — Robot UI / Portal UI dev server
- **tmux** — `scripts/run_server.sh` 가 멀티 윈도우로 서비스 띄움
- **lsof** — `run_server.sh` 의 포트 충돌 사전 경고 (없으면 경고만 생략)
- **[Ollama](https://ollama.com)** — AI Hub 가 호출하는 LLM 런타임

**Robot UI TTS:** Control 이 AI Hub 의 `/voice/tts` 로 **Edge neural MP3** 를 받아 재생합니다 (인터넷 필요). 화자·피치·속도는 루트 `.env` 의 `EDGE_TTS_VOICE`, `EDGE_TTS_PITCH_PCT`, `EDGE_TTS_RATE` 로 조정합니다.

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

#### 1) Python 환경

ROS 2 Jazzy (Ubuntu 24.04) 의 시스템 파이썬에 맞춰 3.12 로 가상환경을 만든다. conda / venv 어느 쪽이든 무방.

```bash
# conda
conda create -n <env> python=3.12 -y
conda activate <env>

# 또는 venv
python3.12 -m venv .venv
source .venv/bin/activate

# 의존성 설치 (활성화된 환경에)
pip install -e .
```

`run_server.sh` / `db-seed.sh` / `ui-admin.sh` 는 활성화된 환경을 자동으로 감지한다 (탐지 우선순위: `VIRTUAL_ENV` → `CONDA_ENV` → `CONDA_DEFAULT_ENV`). 활성화된 환경이 없으면 실행 거부.

#### 2) Ollama 모델 pull

AI Hub 가 사용하는 3개 모델을 미리 받는다 (총 약 6–7 GB):

```bash
ollama serve &              # 데몬이 떠있지 않은 경우
ollama pull qwen2.5:3b      # 의도 분류
ollama pull gemma3:4b       # 잡담 응답
ollama pull bge-m3          # RAG 임베딩
```

모델·호스트 override: `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_CHAT_MODEL` 환경 변수.

#### 3) UI 의존성 (선택)

UI 를 실행할 때만 필요. `scripts/ui-robot.sh` / `scripts/ui-portal.sh` 가 최초 1회 자동으로 `npm install` 을 돌리지만, 미리 받아두려면:

```bash
(cd ui/robot-ui  && npm install)
(cd ui/portal-ui && npm install)
```

#### 4) `.env` 생성

```bash
cp .env.example .env
# 필요한 값 채우기 (Atlassian 토큰은 docs sync 안 쓰면 비워둬도 됨)
```

### 서버 실행 & 종료

```bash
# postgres + AI Hub + Control Service + pgweb 동시 실행 (tmux 세션)
# postgres healthy 후 alembic upgrade head 가 자동으로 돌고 서비스가 뜬다
scripts/run_server.sh

# 서비스 상태 확인
scripts/run_server.sh status

# tmux 세션 종료 (postgres/pgweb는 유지)
scripts/run_server.sh down
```

> seed 데이터 INSERT (메뉴·아이 등 기본 레코드) 는 `scripts/db-seed.sh` 별도 실행. `run_server.sh` 는 스키마 마이그레이션만 처리한다.

PostgreSQL + pgweb 컨테이너 완전 종료 (`down` 이 컨테이너까지 내림):

```bash
docker compose down        # 볼륨은 유지
docker compose down -v     # pg_data 볼륨까지 삭제
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

[설치 4)](#4-env-생성) 단계에서 `.env` 를 만든 뒤 필요한 값만 채운다. 주요 키는 [.env.example](.env.example) 참고.
