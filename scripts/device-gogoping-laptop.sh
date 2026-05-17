#!/usr/bin/env bash
# scripts/device-gogoping-laptop.sh — GogoPing 노트북에서 실행하는 ROS 노드 묶음.
#
# 분산 배포 모델 (gogoping-controller/docs/gogoping-file-structure.md):
#   라즈베리파이 — 모터·센서 (vicpinky_bringup / sllidar / camera UDP / camera_pan)
#   노트북       — Nav2·modes·vision (본 스크립트)
#
# 동작:
#   - tmux 세션 'gogoping-laptop' 안에 window 2개:
#       graph-router : gogoping_navigation graph_router.launch.xml
#                      (vertex 그래프 + 다익스트라 + nav2 위임)
#       modes        : gogoping_modes (FSM + BT 본체 — /gogoping/state publish,
#                      /gogoping/set_goal service. control-server 가 이 둘로 connect.)
#
# 향후 (Day 2~) 추가될 window:
#   - nav2     : nav2 stack (planner + costmap + AMCL) — 실물 launch 미작성
#   - vision   : 사람 추적 / face matching / YOLO 추론 (laptop 노트북 쪽 NPU/GPU 사용)
#
# 사용:
#   scripts/device-gogoping-laptop.sh           # 세션 시작·attach (이미 떠있으면 attach)
#   scripts/device-gogoping-laptop.sh down      # tmux 세션 종료 + 잔여 프로세스 정리
#   scripts/device-gogoping-laptop.sh status    # 세션 상태
#
# 의존:
#   - tmux
#   - /opt/ros/jazzy 설치
#   - repo root 에서 colcon build 완료 (./install/local_setup.zsh 존재)
#   - ROS_DOMAIN_ID 는 호출 셸 환경 그대로 사용 (export 안 함)
#     같은 도메인의 Pi (device-gogoping-pi.sh) 와 ROS_DOMAIN_ID 일치해야 통신
#
# 단축키 (tmux):
#   - 마우스로 하단 status bar 의 window 이름 클릭 → 전환
#   - Ctrl+B 다음 0/1 → window 번호로 전환
#   - Ctrl+B 다음 D → detach (백그라운드 유지)
set -euo pipefail

SESSION="gogoping-laptop"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-up}"

ROS_SETUP="/opt/ros/jazzy/setup.zsh"
WS_SETUP="$REPO_ROOT/install/local_setup.zsh"

if ! command -v tmux &>/dev/null; then
  echo "[device-gogoping-laptop] tmux 가 설치되어 있지 않습니다 (sudo apt install tmux)" >&2
  exit 1
fi

case "$ACTION" in
  up|"")
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      _dead=$(tmux list-panes -t "$SESSION:graph-router" -F '#{pane_dead}' 2>/dev/null | head -1)
      if [[ "$_dead" == "1" ]]; then
        echo "[device-gogoping-laptop] 이전 세션의 pane 이 죽어있음 — 정리 후 재시작"
        tmux kill-session -t "$SESSION"
      else
        echo "[device-gogoping-laptop] 세션 '$SESSION' 이미 떠있음 — attach"
        exec tmux attach -t "$SESSION"
      fi
    fi

    if [[ ! -f "$ROS_SETUP" ]]; then
      echo "[device-gogoping-laptop] ROS Jazzy 가 설치되어 있지 않습니다 ($ROS_SETUP 없음)" >&2
      exit 1
    fi
    if [[ ! -f "$WS_SETUP" ]]; then
      echo "[device-gogoping-laptop] workspace 가 빌드되어 있지 않습니다." >&2
      echo "[device-gogoping-laptop]   cd $REPO_ROOT && colcon build --symlink-install" >&2
      exit 1
    fi

    SOURCE_ENV="source $ROS_SETUP && source $WS_SETUP"

    # tmux 3.4 의 server idle 종료 회피: sleep 으로 띄우고 respawn
    tmux new-session -d -s "$SESSION" -x 200 -y 50 -n graph-router \
      -c "$REPO_ROOT" "sleep infinity"
    tmux set-option -t "$SESSION" -g remain-on-exit on
    tmux respawn-pane -k -t "$SESSION:graph-router" -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_navigation graph_router.launch.xml"

    # window 1: gogoping_modes (FSM + BT 본체)
    tmux new-window -t "$SESSION" -n modes -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 run gogoping_modes gogoping_modes"

    # 마우스 + status bar 설정
    tmux set-option -t "$SESSION" -g mouse on
    tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
    tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
    tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
    tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

    tmux select-window -t "$SESSION:modes"

    echo "[device-gogoping-laptop] 세션 '$SESSION' 시작 — attach"
    echo "[device-gogoping-laptop] ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-<unset>}"
    echo "[device-gogoping-laptop] 하단 status bar 의 'graph-router / modes' 클릭으로 전환"
    exec tmux attach -t "$SESSION"
    ;;
  down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      tmux kill-session -t "$SESSION"
      echo "[device-gogoping-laptop] 세션 '$SESSION' 종료"
    else
      echo "[device-gogoping-laptop] 세션 '$SESSION' 없음"
    fi
    _patterns=(
      "ros2 launch gogoping_navigation graph_router"
      "ros2 run gogoping_modes"
    )
    for p in "${_patterns[@]}"; do
      pkill -TERM -f "$p" 2>/dev/null || true
    done
    sleep 0.5
    for p in "${_patterns[@]}"; do
      pkill -KILL -f "$p" 2>/dev/null || true
    done
    echo "[device-gogoping-laptop] 잔여 프로세스 정리 완료"
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[device-gogoping-laptop] '$SESSION' 실행 중"
      tmux list-windows -t "$SESSION"
    else
      echo "[device-gogoping-laptop] '$SESSION' 없음"
    fi
    ;;
  *)
    echo "usage: $0 [up|down|status]" >&2
    exit 2
    ;;
esac
