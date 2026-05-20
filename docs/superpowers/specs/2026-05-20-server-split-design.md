# Backend / Control 머신 분리 — 설계서

- 작성일: 2026-05-20
- 대상: `scripts/run_server.sh`, `scripts/find_machine_ips.sh`, `service/control-service/control_service/config.py`
- 목적: 현재 한 머신에서 다 돌리는 `run_server.sh` 구조를 유지하면서, 두 머신(같은 LAN) 에 backend(DB+AI) 와 control(+streaming) 을 나눠 띄울 수 있는 운영 옵션을 추가한다.

## 1. 배경

`scripts/run_server.sh` 는 postgres + pgweb + ai-hub + control + streaming 다섯 컴포넌트를 한 호스트의 tmux 세션에서 띄운다. 로컬 개발에는 편하지만, GPU·DB 가 있는 서버와 ROS·로봇 LAN 에 붙은 머신이 분리된 운영 환경을 표현할 방법이 없다. 이번 작업은 두 시나리오를 **둘 다** 가능하게 한다.

- **시나리오 A (로컬 개발)**: 한 머신에서 `scripts/run_server.sh` 로 모두 띄움 — 변경 없음.
- **시나리오 B (분리 운영)**:
  - Backend 박스 (`jungbuntu`) — `scripts/run_db_ai.sh` 가 postgres + pgweb + ai-hub + ollama 책임.
  - Robot 박스 (control 호스트) — `scripts/run_control.sh` 가 control + streaming 책임. backend 박스 IP 는 `shared/machine_ips.json` 에서 자동 lookup.

## 2. 목표 / 비-목표

**목표**

- `run_server.sh` 의 동작·인터페이스를 1바이트도 바꾸지 않는다 (로컬 시나리오 회귀 방지).
- 두 신규 스크립트가 `run_server.sh` 와 같은 UX (tmux 세션, `up | down | status`) 를 갖는다.
- robot 박스에서 backend 박스 위치를 **MAC → IP 자동 조회**로 잡는다. IP 하드코딩 / `.env` 수기 편집 없음.
- `control_service` 의 AI Hub 연결 주소를 env 로 override 가능하게 한다. default 는 현재값(localhost) 유지.

**비-목표 (YAGNI)**

- control 박스 다중 (여러 robot 박스) 운영. 현재는 robot 박스 한 대 가정.
- 인증 강화·TLS·VPN. private LAN 가정에서 평문.
- backend healthcheck 폴링 / 재시도. control 이 backend 보다 먼저 떠도 startup 에서 빠르게 실패 — 재시도 로직은 별도 SR.
- `streaming` 분리. control 과 같이 robot 박스 단일 묶음.
- 알람빅 마이그레이션을 robot 박스에서 실행. backend 박스 단독.

## 3. 토폴로지

```
┌─────────────────────────────────────┐          ┌────────────────────────────────┐
│ Backend 박스  (jungbuntu)            │          │ Robot 박스 (control 호스트)     │
│   docker postgres   :5432  (0.0.0.0) │ ◀────────┤   control      :8000           │
│   docker pgweb      :8081            │   LAN    │     DATABASE_URL → backend     │
│   uvicorn ai-hub    :8001  (0.0.0.0) │ ◀────────┤     AI_HUB_URL   → backend     │
│   host ollama       :11434           │          │   streaming    :8100           │
│                                      │          │     UDP 901X  ← robots (LAN)   │
│   scripts/run_db_ai.sh               │          │   scripts/run_control.sh       │
└─────────────────────────────────────┘          └────────────────────────────────┘
```

postgres / ai-hub 는 이미 `0.0.0.0` 바인딩이라 LAN 노출에 docker / uvicorn 옵션 추가 변경 없음.

## 4. 변경 사항

### 4.1 `scripts/find_machine_ips.sh`

`MACS` 에 한 줄 추가:

```bash
declare -A MACS=(
  [vic]="2c:cf:67:e7:ee:29"
  [leekt]="e8:65:38:23:73:f1"
  [tonyno]="e4:c7:67:61:2f:2e"
  [jungbuntu]="e8:65:38:23:fd:6f"   # backend (DB + AI Hub)
)
```

기존 동작은 동일. 한 머신이라도 못 찾으면 exit 1 정책이 jungbuntu 에도 그대로 적용 — backend 가 꺼져있으면 scan 이 실패하므로 backend 박스가 켜진 상태에서 robot 박스 (또는 다른 머신) 가 `find_machine_ips.sh` 를 한 번 돌려 두는 게 운영 흐름.

### 4.2 `scripts/_run_lib.sh` (신규)

`run_db_ai.sh` / `run_control.sh` 가 source 하는 작은 helper. `run_server.sh` 는 건드리지 않으므로 일부 중복은 허용.

| 함수 | 책임 |
|---|---|
| `_runlib::detect_env` | `VIRTUAL_ENV` / `CONDA_DEFAULT_ENV` 감지, `ENV_DESC` 설정. 활성 환경 없으면 친절한 메시지 + exit 1. |
| `_runlib::wrap_cmd` | 감지한 환경에서 실행할 명령 문자열을 echo (`run_server.sh` 의 `wrap_cmd` 와 동일 시맨틱). |
| `_runlib::warn_port_in_use` | `lsof` 로 TCP / UDP 포트 LISTEN 검사, 경고 출력 (치명적이지 않음). |
| `_runlib::lookup_machine_ip <name>` | `shared/machine_ips.json` 에서 `name.ip` 추출. 파일 없음 / null 이면 stderr 안내 + exit 1. |

### 4.3 `scripts/run_db_ai.sh` (신규) — backend 박스용

tmux 세션 `pingdergarten-backend`, windows: `postgres`, `pgweb`, `ai-hub`.

부트 시퀀스 (현 `run_server.sh` 의 같은 부분과 동일):
1. `docker compose up -d postgres pgweb` → postgres healthy 대기 (30s timeout).
2. `alembic upgrade head` (백엔드 박스 = DB 호스트 = `localhost:5432` 그대로).
3. ollama 데몬 응답 확인 + `REQUIRED_OLLAMA_MODELS` 자동 pull.
4. `python scripts/install_models.py` (YOLO 가중치).
5. 포트 사전 검사: 8001 (ai-hub), 8081 (pgweb). postgres 5432 는 docker 가 알아서.

액션: `up` (default), `down` (tmux kill + `docker compose down`), `status`. `run_server.sh` 와 인터페이스 일치.

### 4.4 `scripts/run_control.sh` (신규) — robot 박스용

부트 시퀀스:
1. `_runlib::lookup_machine_ip jungbuntu` → backend IP 획득. 실패 시 "먼저 `scripts/find_machine_ips.sh` 실행" 안내 + exit 1.
2. 환경변수 export:
   ```bash
   export DATABASE_URL="postgresql+asyncpg://pingder:pingder@${backend_ip}:5432/pingdergarten"
   export AI_HUB_URL="http://${backend_ip}:8001"
   ```
3. 포트 사전 검사: 8000 (control), 8100 (streaming WS), UDP 9013 (gogoping 영상 수신).
4. ROS workspace sourcing (현 `run_server.sh` 의 control window 로직과 동일 — root install → per-workspace 폴백, `NORIARM_FRAMEWORK_PATH` PYTHONPATH).
5. tmux 세션 `pingdergarten-robot`, windows: `control` (uvicorn 8000, `--reload-exclude '*/ros_bridge.py'`), `streaming` (uvicorn 8100).

docker / ollama / install_models / alembic 은 **건너뜀** — backend 박스 책임.

액션: `up` / `down` (tmux kill 만, docker 없음) / `status`.

### 4.5 `service/control-service/control_service/config.py` (수정)

`ai_hub_url` 을 env override 가능하게:

```python
ai_hub_url: str = os.environ.get("AI_HUB_URL", "http://localhost:8001")
```

`load_dotenv` 의 기본 `override=False` 덕분에:
- `run_control.sh` 가 `AI_HUB_URL` 을 export 한 뒤 uvicorn 을 띄우면 → process env 가 `.env` 보다 먼저 박힌 상태이므로 `load_dotenv` 가 덮어쓰지 않음 → backend IP 가 이긴다.
- `run_server.sh` 는 `AI_HUB_URL` 을 export 하지 않으므로 default `http://localhost:8001` 가 그대로 적용 — 회귀 없음.

클래스 docstring 의 "env override 받는 키 목록" 에 `AI_HUB_URL` 추가.

### 4.6 `.env.example` (수정, 작음)

`AI_HUB_URL` 한 줄 추가:

```
# Control → AI Hub. 분리 운영 시 run_control.sh 가 machine_ips.json 으로 자동 override.
# 수동 override 가 필요한 경우에만 값을 바꿔라.
AI_HUB_URL=http://localhost:8001
```

## 5. 두 시나리오 양립 보장

| 항목 | 시나리오 A (`run_server.sh`) | 시나리오 B (`run_db_ai.sh` + `run_control.sh`) |
|---|---|---|
| postgres | docker compose 로 로컬 :5432 | backend 박스 docker compose, robot 박스에서 LAN 으로 접근 |
| ai-hub | localhost:8001 | backend 박스 0.0.0.0:8001, robot 박스가 LAN 으로 접근 |
| `DATABASE_URL` | `.env` default (localhost) | `run_control.sh` 가 backend IP 로 export — `.env` 보다 우선 |
| `AI_HUB_URL` | export 안 함 → `config.py` default (localhost) | `run_control.sh` 가 backend IP 로 export |
| alembic | run_server 가 수행 | backend 박스의 `run_db_ai.sh` 가 수행 |
| ollama / install_models | run_server 가 수행 | backend 박스의 `run_db_ai.sh` 가 수행 |

핵심: `run_server.sh` 와 `config.py` default 가 동일한 값(`localhost:8001`, `localhost:5432`) 이라 시나리오 A 동작은 그대로 유지.

## 6. 테스트 계획

- 로컬 회귀: `scripts/run_server.sh up` → `down` 정상. control window 의 health endpoint 가 ai-hub 와 통신 (`http://localhost:8001`) — 기존 동작 그대로.
- backend 박스 단독 부트: `run_db_ai.sh up` → `curl http://localhost:8001/health` OK, `pgweb` 웹 UI 접속 OK, `psql -h localhost -U pingder -d pingdergarten` OK.
- robot 박스 부트: `find_machine_ips.sh` 가 `jungbuntu` 항목을 채운 뒤 `run_control.sh up` → control window 로그에 backend IP 가 박힌 `DATABASE_URL` / `AI_HUB_URL` 출력. health endpoint 호출 시 ai-hub 가 backend 박스에서 응답.
- backend 박스 꺼진 채 `run_control.sh` 띄움: control startup 이 빠르게 실패하고 tmux window 에 에러 표시 (remain-on-exit 로 보존).
- `shared/machine_ips.json` 없거나 `jungbuntu.ip = null` 인 상태: `run_control.sh` 가 즉시 안내 + exit 1.

## 7. 미해결 / 추후

- backend 박스가 일시 다운된 경우의 control 자동 재연결. 현재는 uvicorn 재기동 / httpx 요청 시점 재시도에 의존. healthcheck 폴링은 SR 로 분리.
- `find_machine_ips.sh` 의 자동화 (cron / on-boot). 현재는 운영자가 수동으로 1회 실행 가정.
- 운영 보안 (postgres 비밀번호·TLS·LAN 분리). 현재는 dev/내부망 가정.
