#!/usr/bin/env bash
# scripts/run_control.sh — robot 박스용 (control + streaming).
#
# backend(DB+AI) 박스 IP 는 shared/machine_ips.json 에서 'ai-server' 키로 lookup.
# DATABASE_URL / AI_HUB_URL 을 그 IP 로 export 한 뒤 control / streaming uvicorn 기동.
#
# 사전 조건:
#   - backend 박스가 같은 LAN 에 켜져있고 scripts/run_db_ai.sh 가 동작 중.
#   - 이 박스(또는 같은 LAN 의 다른 박스)에서 scripts/find_machine_ips.sh 가 최근 실행돼
#     shared/machine_ips.json 에 ai-server 항목이 채워져 있음.
#
# 사용:
#   scripts/run_control.sh           # 세션 시작·attach
#   scripts/run_control.sh down      # tmux 세션 종료 (docker 미사용)
#   scripts/run_control.sh status    # 세션 상태
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_run_lib.sh"

SESSION="pingdergarten-robot"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ACTION="${1:-up}"
BACKEND_NAME="ai-server"

if ! command -v tmux &>/dev/null; then
  echo "[run_control] tmux 가 필요합니다." >&2
  exit 1
fi

case "$ACTION" in
  up|"")
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[run_control] 세션 '$SESSION' 이미 떠있음 — attach"
      exec tmux attach -t "$SESSION"
    fi

    _runlib::detect_env

    BACKEND_IP="$(_runlib::lookup_machine_ip "$BACKEND_NAME")"
    echo "[run_control] backend '$BACKEND_NAME' → $BACKEND_IP"

    export DATABASE_URL="postgresql+asyncpg://pingder:pingder@${BACKEND_IP}:5432/pingdergarten"
    export AI_HUB_URL="http://${BACKEND_IP}:8001"
    echo "[run_control] DATABASE_URL=$DATABASE_URL"
    echo "[run_control] AI_HUB_URL=$AI_HUB_URL"

    _runlib::warn_port_in_use 8000 tcp
    _runlib::warn_port_in_use 8100 tcp
    _runlib::warn_port_in_use 9013 udp

    # ROS workspace sourcing — run_server.sh 의 control window 와 동일 정책:
    # root install 이 있으면 그것만 source, 없으면 per-workspace 폴백.
    NORIARM_FRAMEWORK_PATH="$REPO_ROOT/controller/noriarm-controller/src/noriarm_framework"
    ROS_SETUP="/opt/ros/jazzy/setup.bash"
    ROOT_WS_SETUP="$REPO_ROOT/install/setup.bash"
    EDUPING_WS_SETUP="$REPO_ROOT/controller/eduping-controller/install/setup.bash"
    NORIARM_WS_SETUP="$REPO_ROOT/controller/noriarm-controller/install/setup.bash"
    GOGOPING_WS_SETUP="$REPO_ROOT/controller/gogoping-controller/install/setup.bash"

    if [[ ! -f "$ROOT_WS_SETUP" && ! -f "$EDUPING_WS_SETUP" && ! -f "$NORIARM_WS_SETUP" && ! -f "$GOGOPING_WS_SETUP" ]]; then
      echo "[run_control] ⚠ 워크스페이스 빌드 결과 없음 — control 의 일부 기능이 거절될 수 있습니다." >&2
      echo "[run_control]   cd $REPO_ROOT && source $ROS_SETUP && colcon build --symlink-install 후 재실행." >&2
    fi

    if [[ -f "$ROOT_WS_SETUP" ]]; then
      WS_SOURCING="source $ROOT_WS_SETUP"
    else
      WS_SOURCING=""
      [[ -f "$EDUPING_WS_SETUP" ]]  && WS_SOURCING="$WS_SOURCING source $EDUPING_WS_SETUP;"
      [[ -f "$NORIARM_WS_SETUP" ]]  && WS_SOURCING="$WS_SOURCING source $NORIARM_WS_SETUP;"
      [[ -f "$GOGOPING_WS_SETUP" ]] && WS_SOURCING="$WS_SOURCING source $GOGOPING_WS_SETUP;"
    fi

    CONTROL_CMD="$(_runlib::wrap_cmd uvicorn control_service.main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude '*/ros_bridge.py')"

    # noriarm store_play 의 runner subprocess 는 별도 venv(store_play) 의 python 으로 spawn.
    # control_service(pingdergarten venv)와 runner(store_play venv) 분리 — lerobot bi_omx_*
    # 커스텀 코드가 store_play venv 의 lerobot-upstream 에 editable 설치돼 있음.
    # NORIARM_STOREPLAY_PYTHON / _PYTHONPATH 가 없으면 runner 가 pingdergarten venv 로 spawn 돼서
    # ModuleNotFoundError: lerobot.robots.bi_omx_follower 로 죽음 (메모리 noriarm_venv_deployment.md).
    STOREPLAY_PYTHON="/home/kyle/venv/store_play/bin/python"

    tmux new-session -d -s "$SESSION" -x 200 -y 50 -n control -c "$REPO_ROOT" \
      "bash -c 'export DATABASE_URL=\"$DATABASE_URL\"; export AI_HUB_URL=\"$AI_HUB_URL\"; export NORIARM_STOREPLAY_PYTHON=\"$STOREPLAY_PYTHON\"; export NORIARM_STOREPLAY_PYTHONPATH=\"$NORIARM_FRAMEWORK_PATH\"; [ -f $ROS_SETUP ] && source $ROS_SETUP; $WS_SOURCING; export PYTHONPATH=\"$NORIARM_FRAMEWORK_PATH:\${PYTHONPATH:-}\"; exec $CONTROL_CMD'"
    tmux set-option -t "$SESSION" -g remain-on-exit on

    # --reload 기본 OFF: reloader watcher 의 multiprocessing-fork 자식이 시간당 GB 로 새다
    # OOM (2026-05-30, RSS 7.6GB KILL) + 재시작이 누수 측정 baseline 리셋. dev 가 본인만
    # 자동 재시작 원하면 STREAMING_RELOAD=1 을 본인 env 에 (팀 기본 OFF). 추적은 /debug/memtop.
    STREAMING_RELOAD_FLAG=""
    case "${STREAMING_RELOAD:-0}" in 1|true|TRUE|yes|on) STREAMING_RELOAD_FLAG="--reload" ;; esac
    tmux new-window -t "$SESSION" -n streaming -c "$REPO_ROOT" \
      "bash -c 'export DATABASE_URL=\"$DATABASE_URL\"; export AI_HUB_URL=\"$AI_HUB_URL\"; exec $(_runlib::wrap_cmd uvicorn control_service.streaming.app:app --host 0.0.0.0 --port 8100 $STREAMING_RELOAD_FLAG)'"

    # EduPing depth view ROS 스택 — d435 카메라 + ROS→WS 스트리머 + highfive_sim
    # (IK + sim_twin + depth_mask + move_group). DepthViewer 가 사용. 항상 떠 있어야
    # control-service 의 bridge 가 stale handle 없이 깨끗하게 동작. depth_session.py
    # 가 pgrep 로 감지해서 자동 attach. D435 미연결 시에도 window 만 에러 메시지 +
    # remain-on-exit 로 보존 — 다른 stack 영향 없음.
    #
    # control window 와 WS_SOURCING 정책이 다른 이유:
    #   control 은 root install (eduarm 만 있어도 OK) 하나만 source 해서 가벼움.
    #   highfive_sim 은 openarm_description / openarm_bimanual_moveit_config 같은
    #   controller/eduping-controller/install 의 추가 패키지가 반드시 필요 → 두
    #   workspace 모두 source. 순서: root 먼저 → eduping overlay 위에.
    # WS_SOURCING terminator 가 분기마다 일관성 없음 (root 하나만 = no ";", multi =
    # 각 "; ") → 결합 시 ";; " 같은 syntax error 발생 가능. trailing ";" 정규화 후
    # 결합.
    DEPTH_WS_SOURCING="${WS_SOURCING%;}"
    if [[ -f "$EDUPING_WS_SETUP" && "$WS_SOURCING" != *"$EDUPING_WS_SETUP"* ]]; then
      if [[ -n "$DEPTH_WS_SOURCING" ]]; then
        DEPTH_WS_SOURCING="$DEPTH_WS_SOURCING; source $EDUPING_WS_SETUP"
      else
        DEPTH_WS_SOURCING="source $EDUPING_WS_SETUP"
      fi
    fi
    DEPTH_ROS_PREFIX="[ -f $ROS_SETUP ] && source $ROS_SETUP; $DEPTH_WS_SOURCING"

    tmux new-window -t "$SESSION" -n d435 -c "$REPO_ROOT" \
      "bash -c '$DEPTH_ROS_PREFIX; exec ros2 launch eduarm d435_camera.launch.py \
         depth_width:=640 depth_height:=480 color_width:=640 color_height:=480 fps:=15'"

    # streamer 는 system python (/usr/bin/python3) 강제 — eduarm install 의 ROS
    # python 패키지 (cv_bridge 등) 가 numpy 1.x 로 빌드되어 conda pdg 의 numpy 2.x
    # 와 ABI 충돌. depth_session.py 의 spawn 도 동일하게 /usr/bin/python3 사용.
    tmux new-window -t "$SESSION" -n streamer -c "$REPO_ROOT" \
      "bash -c '$DEPTH_ROS_PREFIX; \
         export PYTHONPATH=\"$REPO_ROOT/service/control-service:\${PYTHONPATH:-}\"; \
         exec /usr/bin/python3 -m eduarm.d435_depth_streamer --server-host 127.0.0.1'"

    tmux new-window -t "$SESSION" -n highfive -c "$REPO_ROOT" \
      "bash -c '$DEPTH_ROS_PREFIX; exec ros2 launch eduarm highfive_sim.launch.py'"

    tmux set-option -t "$SESSION" -g mouse on
    tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
    tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
    tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
    tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

    tmux select-window -t "$SESSION:control"
    echo "[run_control] 세션 '$SESSION' 시작 — attach"
    exec tmux attach -t "$SESSION"
    ;;
  down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      tmux kill-session -t "$SESSION"
      echo "[run_control] 세션 '$SESSION' 종료"
    else
      echo "[run_control] 세션 '$SESSION' 없음"
    fi
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[run_control] '$SESSION' 실행 중"
      tmux list-windows -t "$SESSION"
    else
      echo "[run_control] '$SESSION' 없음"
    fi
    ;;
  *)
    echo "usage: $0 [up|down|status]" >&2
    exit 2
    ;;
esac
