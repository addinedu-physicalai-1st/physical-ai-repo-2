#!/usr/bin/env bash
# scripts/device-gogoping-sim.sh — GogoPing 가제보 시뮬레이션 launcher.
#
# 동작:
#   - tmux 세션 'gogoping-sim' 안에 window 1개 (gazebo)
#   - gazebo : gogoping_bringup sim.launch.py
#              (gogoping_navigation/launch_sim_with_pinky.launch.xml 을
#               namespace=gogoping 으로 include + sim_status_publisher 노드)
#
# 사용:
#   scripts/device-gogoping-sim.sh           # 세션 시작·attach (이미 떠있으면 attach)
#   scripts/device-gogoping-sim.sh down      # tmux 세션 + 잔여 가제보·브리지 정리
#   scripts/device-gogoping-sim.sh status    # 세션 상태
#
# 의존:
#   - tmux
#   - /opt/ros/jazzy 설치
#   - repo root 에서 colcon build 완료 (./install/setup.bash 존재)
#   - ROS_DOMAIN_ID 는 호출 셸 환경 그대로 사용 (export 안 함)
#
# 단축키 (tmux):
#   - Ctrl+B 다음 D → detach (백그라운드 유지)
set -euo pipefail

SESSION="gogoping-sim"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-up}"

ROS_SETUP="/opt/ros/jazzy/setup.zsh"
WS_SETUP="$REPO_ROOT/install/local_setup.zsh"

if ! command -v tmux &>/dev/null; then
  echo "[device-gogoping-sim] tmux 가 설치되어 있지 않습니다 (sudo apt install tmux)" >&2
  exit 1
fi

case "$ACTION" in
  up|"")
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      # remain-on-exit 때문에 ros2 launch 가 죽어도 pane 은 유지된다. 죽은 pane 에
      # 그대로 attach 하면 가제보가 안 뜨니, 세션 정리 후 아래 재기동 흐름으로.
      _dead=$(tmux list-panes -t "$SESSION:gazebo" -F '#{pane_dead}' 2>/dev/null | head -1)
      if [[ "$_dead" == "1" ]]; then
        echo "[device-gogoping-sim] 이전 세션의 pane 이 죽어있음 — 정리 후 재시작"
        tmux kill-session -t "$SESSION"
      else
        echo "[device-gogoping-sim] 세션 '$SESSION' 이미 떠있음 — attach"
        exec tmux attach -t "$SESSION"
      fi
    fi

    if [[ ! -f "$ROS_SETUP" ]]; then
      echo "[device-gogoping-sim] ROS Jazzy 가 설치되어 있지 않습니다 ($ROS_SETUP 없음)" >&2
      exit 1
    fi
    if [[ ! -f "$WS_SETUP" ]]; then
      echo "[device-gogoping-sim] workspace 가 빌드되어 있지 않습니다." >&2
      echo "[device-gogoping-sim]   cd $REPO_ROOT && colcon build --symlink-install" >&2
      exit 1
    fi

    # 같은 도메인에 두 개의 가제보가 뜨면 토픽 충돌. 외부에서 띄운 gz sim 도 차단.
    # pgrep 매칭 없을 때의 exit 1 이 pipefail+errexit 로 스크립트를 죽이지 않도록 잠시 해제.
    set +o pipefail
    _existing_gz=$(pgrep -af "gz sim" 2>/dev/null | grep -v "ruby .*gz sim" | wc -l)
    set -o pipefail
    if [[ "$_existing_gz" -gt 0 ]]; then
      echo "[device-gogoping-sim] 이미 gz sim 프로세스가 실행 중입니다 ($_existing_gz 개)." >&2
      echo "[device-gogoping-sim] scripts/device-gogoping-sim.sh down 으로 정리해 주세요." >&2
      exit 1
    fi

    SOURCE_ENV="source $ROS_SETUP && source $WS_SETUP"

    # tmux 3.4 의 server idle 종료 회피: sleep 으로 띄우고 respawn
    tmux new-session -d -s "$SESSION" -x 200 -y 50 -n gazebo \
      -c "$REPO_ROOT" "sleep infinity"
    tmux set-option -t "$SESSION" -g remain-on-exit on
    tmux respawn-pane -k -t "$SESSION:gazebo" -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_bringup sim.launch.py"

    # window 1: graph-router (vertex 그래프 + 다익스트라 + nav2 위임)
    tmux new-window -t "$SESSION" -n graph-router -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_navigation graph_router.launch.xml"

    # 마우스 + status bar 설정
    tmux set-option -t "$SESSION" -g mouse on
    tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
    tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
    tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
    tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

    tmux select-window -t "$SESSION:gazebo"

    echo "[device-gogoping-sim] 세션 '$SESSION' 시작 — attach"
    echo "[device-gogoping-sim] ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-<unset>}"
    exec tmux attach -t "$SESSION"
    ;;
  down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      tmux kill-session -t "$SESSION"
      echo "[device-gogoping-sim] 세션 '$SESSION' 종료"
    else
      echo "[device-gogoping-sim] 세션 '$SESSION' 없음"
    fi
    # gz sim 의 server·gui 자식은 tmux SIGHUP 으로 회수되지 않아 명시 정리. SIGTERM → SIGKILL.
    _patterns=(
      "ros2 launch gogoping_bringup sim"
      "gz sim"
      "ruby .*gz sim"
      "parameter_bridge"
      "ros_gz_image"
      "robot_state_publisher"
      "sim_status_publisher"
    )
    for p in "${_patterns[@]}"; do
      pkill -TERM -f "$p" 2>/dev/null || true
    done
    sleep 0.5
    for p in "${_patterns[@]}"; do
      pkill -KILL -f "$p" 2>/dev/null || true
    done
    echo "[device-gogoping-sim] 가제보·브리지 잔여 프로세스 정리 완료"
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[device-gogoping-sim] '$SESSION' 실행 중"
      tmux list-windows -t "$SESSION"
    else
      echo "[device-gogoping-sim] '$SESSION' 없음"
    fi
    ;;
  *)
    echo "usage: $0 [up|down|status]" >&2
    exit 2
    ;;
esac
