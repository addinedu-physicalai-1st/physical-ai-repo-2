#!/usr/bin/env bash
# scripts/run_db_ai.sh — backend 박스용 (postgres + pgweb + ai-hub).
#
# run_server.sh 의 부분집합 — control / streaming 은 robot 박스의
# scripts/run_control.sh 가 책임. 로컬 all-in-one 시나리오는 run_server.sh 그대로.
#
# 사용:
#   scripts/run_db_ai.sh           # 세션 시작·attach
#   scripts/run_db_ai.sh down      # tmux + postgres/pgweb 컨테이너 종료
#   scripts/run_db_ai.sh status    # 세션 상태
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_run_lib.sh"

SESSION="pingdergarten-backend"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ACTION="${1:-up}"

if ! command -v tmux &>/dev/null; then
  echo "[run_db_ai] tmux 가 필요합니다." >&2
  exit 1
fi

case "$ACTION" in
  up|"")
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[run_db_ai] 세션 '$SESSION' 이미 떠있음 — attach"
      exec tmux attach -t "$SESSION"
    fi

    _runlib::detect_env

    cd "$REPO_ROOT"
    echo "[run_db_ai] postgres + pgweb 컨테이너 시작..."
    docker compose up -d postgres pgweb

    echo "[run_db_ai] postgres healthy 대기..."
    healthy=0
    for _ in {1..30}; do
      if docker compose ps postgres --format json 2>/dev/null | grep -q '"Health":"healthy"'; then
        healthy=1
        break
      fi
      sleep 1
    done
    if [[ $healthy -ne 1 ]]; then
      echo "[run_db_ai] postgres healthy 실패 — 'docker compose logs postgres' 확인" >&2
      exit 1
    fi
    echo "[run_db_ai] postgres ready (:5432) / pgweb ready (http://localhost:8081)"

    echo "[run_db_ai] alembic upgrade head ($ENV_DESC)"
    if ! eval "$(_runlib::wrap_cmd alembic -c db/control-db/control_db/alembic.ini upgrade head)"; then
      echo "[run_db_ai] ⚠ alembic 실패" >&2
      exit 1
    fi

    if ! command -v ollama &>/dev/null; then
      echo "[run_db_ai] ollama CLI 가 PATH 에 없음 — https://ollama.com/download" >&2
      exit 1
    fi
    if ! ollama list &>/dev/null; then
      echo "[run_db_ai] ollama 데몬 무응답 — 'ollama serve' 실행 후 재시도" >&2
      exit 1
    fi
    echo "[run_db_ai] 필수 ollama 모델 점검 ($ENV_DESC)"
    mapfile -t REQUIRED_MODELS < <(eval "$(_runlib::wrap_cmd python -m ai_service.config)")
    for m in "${REQUIRED_MODELS[@]}"; do
      if ollama show "$m" &>/dev/null; then
        echo "  ✓ $m"
      else
        echo "  ↓ $m 없음 — pull..."
        if ! ollama pull "$m"; then
          echo "[run_db_ai] ollama pull $m 실패" >&2
          exit 1
        fi
      fi
    done

    echo "[run_db_ai] ML 모델 가중치 확인"
    if ! eval "$(_runlib::wrap_cmd python scripts/install_models.py)"; then
      echo "[run_db_ai] ⚠ install_models 실패" >&2
      exit 1
    fi

    _runlib::warn_port_in_use 8001 tcp
    _runlib::warn_port_in_use 8081 tcp

    tmux new-session -d -s "$SESSION" -x 200 -y 50 -n postgres -c "$REPO_ROOT" \
      'docker compose logs -f postgres'
    tmux set-option -t "$SESSION" -g remain-on-exit on

    tmux new-window -t "$SESSION" -n pgweb -c "$REPO_ROOT" \
      'docker compose logs -f pgweb'

    tmux new-window -t "$SESSION" -n ai-hub -c "$REPO_ROOT" \
      "$(_runlib::wrap_cmd uvicorn ai_service.hub:app --host 0.0.0.0 --port 8001 --reload)"

    tmux set-option -t "$SESSION" -g mouse on
    tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
    tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
    tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
    tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

    tmux select-window -t "$SESSION:ai-hub"
    echo "[run_db_ai] 세션 '$SESSION' 시작 — attach"
    exec tmux attach -t "$SESSION"
    ;;
  down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      tmux kill-session -t "$SESSION"
      echo "[run_db_ai] 세션 '$SESSION' 종료"
    else
      echo "[run_db_ai] 세션 '$SESSION' 없음"
    fi
    echo "[run_db_ai] 컨테이너 종료..."
    cd "$REPO_ROOT"
    docker compose down
    echo "[run_db_ai] 완료 — 볼륨(pg_data) 유지. 완전 삭제는 'docker compose down -v'"
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[run_db_ai] '$SESSION' 실행 중"
      tmux list-windows -t "$SESSION"
    else
      echo "[run_db_ai] '$SESSION' 없음"
    fi
    ;;
  *)
    echo "usage: $0 [up|down|status]" >&2
    exit 2
    ;;
esac
