#!/usr/bin/env bash
# scripts/run_server.sh — postgres + pgweb + AI Hub + Control + Streaming 을 한 번에 실행.
#
# 동작:
#   - postgres + pgweb docker 컨테이너 자동 기동 (없으면 띄우고, healthy 까지 대기)
#   - tmux 세션 'pingdergarten' 안에 window 5개 (postgres / pgweb / ai-hub / control / streaming)
#   - 한 화면엔 1개 window 만 표시. 하단 status bar 의 window 이름을 마우스 클릭으로 전환
#   - pgweb DB 뷰어: http://localhost:8081
#   - streaming WS: ws://localhost:8100/ws/video-stream (SR-CAM-002, 영상 fan-out)
#
# 사용:
#   scripts/run_server.sh           # 세션 시작·attach (이미 떠있으면 attach)
#   scripts/run_server.sh down      # tmux 세션 + postgres/pgweb 컨테이너 종료
#   scripts/run_server.sh status    # 세션 상태 + window 목록
#
# 의존:
#   - tmux, docker
#   - 활성화된 Python 환경 (conda env 또는 venv) — 환경 이름은 팀원마다 다르며 스크립트가 자동 감지한다 (CONDA_DEFAULT_ENV / VIRTUAL_ENV)
#   - host 에 ollama 가 떠있어야 한다 (`ollama serve` 또는 macOS 앱)
#
# 단축키 (tmux):
#   - 마우스로 하단 status bar 의 window 이름 클릭 → 전환
#   - Ctrl+B 다음 0/1/2 → window 번호로 전환
#   - Ctrl+B 다음 D → detach (백그라운드 유지)
set -euo pipefail

SESSION="pingdergarten"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-up}"

# 활성 환경 감지: VIRTUAL_ENV (venv) → CONDA_ENV → CONDA_DEFAULT_ENV(base 제외)
# wrap_cmd <cmd> <args...> → 환경 안에서 실행할 명령 문자열을 stdout 으로 출력
ENV_DESC=""
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  ENV_DESC="venv:$VIRTUAL_ENV"
  wrap_cmd() { echo "$VIRTUAL_ENV/bin/$*"; }
else
  ENV_NAME="${CONDA_ENV:-}"
  if [[ -z "$ENV_NAME" && -n "${CONDA_DEFAULT_ENV:-}" && "${CONDA_DEFAULT_ENV}" != "base" ]]; then
    ENV_NAME="$CONDA_DEFAULT_ENV"
  fi
  if [[ -z "$ENV_NAME" ]]; then
    echo "[run_server] 활성화된 conda/venv 환경이 없습니다. 'conda activate <env>' 또는 venv 활성화 후 실행하세요." >&2
    exit 1
  fi
  ENV_DESC="conda:$ENV_NAME"
  wrap_cmd() { echo "conda run --no-capture-output -n $ENV_NAME $*"; }
fi

if ! command -v tmux &>/dev/null; then
  echo "[run_server] tmux 가 설치되어 있지 않습니다 (brew install tmux)" >&2
  exit 1
fi

case "$ACTION" in
  up|"")
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[run_server] 세션 '$SESSION' 이미 떠있음 — attach"
      exec tmux attach -t "$SESSION"
    fi

    # postgres + pgweb 기동 (이미 떠있으면 no-op) + healthy 대기
    cd "$REPO_ROOT"
    echo "[run_server] postgres + pgweb 컨테이너 시작..."
    docker compose up -d postgres pgweb

    echo "[run_server] postgres healthy 대기..."
    healthy=0
    for _ in {1..30}; do
      if docker compose ps postgres --format json 2>/dev/null | grep -q '"Health":"healthy"'; then
        healthy=1
        break
      fi
      sleep 1
    done
    if [[ $healthy -ne 1 ]]; then
      echo "[run_server] postgres healthy 안 됨 — 'docker compose logs postgres' 로 확인" >&2
      exit 1
    fi
    echo "[run_server] postgres ready (localhost:5432) / pgweb ready (http://localhost:8081)"

    # alembic upgrade head — 첫 실행 시 스키마 생성, 이미 최신이면 no-op
    echo "[run_server] alembic upgrade head ($ENV_DESC)"
    if ! eval "$(wrap_cmd alembic -c db/control-db/control_db/alembic.ini upgrade head)"; then
      echo "[run_server] ⚠ alembic 마이그레이션 실패 — 'scripts/db-seed.sh' 로 수동 확인" >&2
      exit 1
    fi

    # Ollama 점검 — 데몬 응답 확인 + 필수 모델 자동 pull. 모델 목록은 service/ai-service/ai_service/config.py
    # 의 REQUIRED_OLLAMA_MODELS 가 단일 source-of-truth.
    # 모델 존재 확인은 `ollama show` 로 한다 — `bge-m3` 와 `bge-m3:latest` 처럼 태그
    # 생략/명시를 동일하게 처리하므로 `ollama list` 파싱보다 안전.
    if ! command -v ollama &>/dev/null; then
      echo "[run_server] ollama CLI 가 PATH 에 없습니다 — https://ollama.com/download" >&2
      exit 1
    fi
    if ! ollama list &>/dev/null; then
      echo "[run_server] ollama 데몬 응답 없음 — 'ollama serve' 또는 macOS 앱 실행 후 재시도" >&2
      exit 1
    fi
    echo "[run_server] 필수 ollama 모델 점검 ($ENV_DESC)"
    mapfile -t REQUIRED_MODELS < <(eval "$(wrap_cmd python -m ai_service.config)")
    for m in "${REQUIRED_MODELS[@]}"; do
      if ollama show "$m" &>/dev/null; then
        echo "  ✓ $m"
      else
        echo "  ↓ $m 없음 — pull..."
        if ! ollama pull "$m"; then
          echo "[run_server] ollama pull $m 실패" >&2
          exit 1
        fi
      fi
    done

    # YOLO 등 ML 모델 가중치 자동 다운로드 (없으면) — 첫 실행만 ~25MB 받음
    echo "[run_server] ML 모델 가중치 확인"
    if ! eval "$(wrap_cmd python scripts/install_models.py)"; then
      echo "[run_server] ⚠ 모델 다운로드 실패 — 인터넷 확인 후 'python scripts/install_models.py' 수동 실행" >&2
      exit 1
    fi

    # 포트 충돌 사전 경고 (치명적이진 않음 — 사용자가 알아서 처리)
    # 8000=control, 8001=ai-hub, 8081=pgweb, 8100=streaming(WS)
    for port in 8000 8001 8081 8100; do
      if lsof -i ":$port" -P -sTCP:LISTEN &>/dev/null; then
        echo "[run_server] ⚠ 포트 $port 가 이미 사용 중 — 해당 서비스가 바인드 실패하면 window 에 에러가 표시됩니다." >&2
      fi
    done
    # streaming UDP 영상 수신 포트 (이번 SR: gogoping primary 9013 만 활성)
    if command -v lsof &>/dev/null; then
      if lsof -i ":9013" -P -sUDP:LISTEN &>/dev/null; then
        echo "[run_server] ⚠ UDP 9013 가 이미 사용 중 — streaming 의 gogoping 영상 수신이 실패할 수 있습니다." >&2
      fi
    fi

    # remain-on-exit on: 프로세스 종료해도 window 유지 (에러 메시지 보고 디버깅 가능)
    tmux new-session -d -s "$SESSION" -x 200 -y 50 -n postgres -c "$REPO_ROOT" \
      'docker compose logs -f postgres'
    tmux set-option -t "$SESSION" -g remain-on-exit on

    # window 1: pgweb :8081 (DB 뷰어)
    tmux new-window -t "$SESSION" -n pgweb -c "$REPO_ROOT" \
      'docker compose logs -f pgweb'

    # window 2: ai-hub :8001
    tmux new-window -t "$SESSION" -n ai-hub -c "$REPO_ROOT" \
      "$(wrap_cmd uvicorn ai_service.hub:app --host 0.0.0.0 --port 8001 --reload)"

    # window 3: control :8000 — NoriArm + Eduping(OpenArm) + Gogoping 통합용 ROS 환경.
    # ROS jazzy → install overlay → noriarm_framework PYTHONPATH 순서.
    # 권장: repo root 에서 `colcon build --symlink-install` 한 번으로 모든 패키지 빌드 → $REPO_ROOT/install/ 에
    # 통합 setup.bash 생성. 그 한 줄만 source. per-workspace install/ (eduping-controller/, noriarm-controller/) 은
    # 과거에 빌드해뒀던 잔재일 수 있고 part-build 면 "not found" 경고가 다발 → 루트 install 이 있을 땐 무시.
    NORIARM_FRAMEWORK_PATH="$REPO_ROOT/controller/noriarm-controller/src/noriarm_framework"
    ROS_SETUP="/opt/ros/jazzy/setup.bash"
    ROOT_WS_SETUP="$REPO_ROOT/install/setup.bash"
    EDUPING_WS_SETUP="$REPO_ROOT/controller/eduping-controller/install/setup.bash"
    NORIARM_WS_SETUP="$REPO_ROOT/controller/noriarm-controller/install/setup.bash"
    GOGOPING_WS_SETUP="$REPO_ROOT/controller/gogoping-controller/install/setup.bash"
    # --reload-exclude '*/ros_bridge.py': rclpy 노드를 들고있는 4개 bridge 파일은
    # 자동 reload 제외 (uvicorn worker 재시작 시 rclpy 자원 정리가 깨끗하지 않아 wedge 발생).
    # 해당 파일 수정 시에는 control window 에서 Ctrl+C 후 수동 재실행 필요.
    CONTROL_CMD="$(wrap_cmd uvicorn control_service.main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude '*/ros_bridge.py')"

    if [[ ! -f "$ROOT_WS_SETUP" && ! -f "$EDUPING_WS_SETUP" && ! -f "$NORIARM_WS_SETUP" && ! -f "$GOGOPING_WS_SETUP" ]]; then
      echo "[run_server] ⚠ 워크스페이스 빌드 결과 없음 — /api/eduping/*, graph routing 등 일부 기능이 거절됩니다." >&2
      echo "[run_server]   cd $REPO_ROOT && source $ROS_SETUP && colcon build --symlink-install 후 재실행." >&2
    fi

    # source 전략: root install 이 있으면 그것만 (모든 패키지 통합). 없으면 per-workspace 폴백.
    # 둘 다 source 하면 stale per-workspace 의 미완성 setup.bash 가 "not found" 경고를 다발시킨다.
    if [[ -f "$ROOT_WS_SETUP" ]]; then
      WS_SOURCING="source $ROOT_WS_SETUP"
    else
      WS_SOURCING=""
      [[ -f "$EDUPING_WS_SETUP" ]] && WS_SOURCING="$WS_SOURCING source $EDUPING_WS_SETUP;"
      [[ -f "$NORIARM_WS_SETUP" ]] && WS_SOURCING="$WS_SOURCING source $NORIARM_WS_SETUP;"
      [[ -f "$GOGOPING_WS_SETUP" ]] && WS_SOURCING="$WS_SOURCING source $GOGOPING_WS_SETUP;"
    fi

    tmux new-window -t "$SESSION" -n control -c "$REPO_ROOT" \
      "bash -c '[ -f $ROS_SETUP ] && source $ROS_SETUP; $WS_SOURCING; export PYTHONPATH=\"$NORIARM_FRAMEWORK_PATH:\${PYTHONPATH:-}\"; exec $CONTROL_CMD'"

    # window 4: streaming :8100 (WS /ws/video-stream + UDP 9013 영상 수신, SR-CAM-002)
    tmux new-window -t "$SESSION" -n streaming -c "$REPO_ROOT" \
      "$(wrap_cmd uvicorn control_service.streaming.app:app --host 0.0.0.0 --port 8100 --reload)"

    # 마우스 + status bar 설정 (window 이름 클릭으로 전환 가능)
    tmux set-option -t "$SESSION" -g mouse on
    tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
    tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
    tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
    tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

    # control window 로 attach (가장 자주 보는 화면)
    tmux select-window -t "$SESSION:control"

    echo "[run_server] 세션 '$SESSION' 시작 — attach"
    echo "[run_server] 하단 status bar 의 'postgres / pgweb / ai-hub / control / streaming' 클릭으로 전환"
    exec tmux attach -t "$SESSION"
    ;;
  down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      tmux kill-session -t "$SESSION"
      echo "[run_server] 세션 '$SESSION' 종료"
    else
      echo "[run_server] 세션 '$SESSION' 없음"
    fi

    echo "[run_server] 컨테이너 종료..."
    cd "$REPO_ROOT"
    docker compose down
    echo "[run_server] 완료 — 볼륨(pg_data)은 유지됨. 완전 삭제는 'docker compose down -v'"
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[run_server] '$SESSION' 실행 중"
      tmux list-windows -t "$SESSION"
    else
      echo "[run_server] '$SESSION' 없음"
    fi
    ;;
  *)
    echo "usage: $0 [up|down|status]" >&2
    exit 2
    ;;
esac
