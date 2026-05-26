#!/usr/bin/env bash
# scripts/device-gogoping-pi.sh — GogoPing 라즈베리파이에서 실행하는 ROS 노드 묶음.
#
# 분산 배포 모델 (gogoping-controller/docs/gogoping-file-structure.md):
#   라즈베리파이 — 모터·센서 (본 스크립트)
#   노트북       — Nav2 + perception + follow + D435 camera + camera_pan (scripts/device-gogoping-laptop.sh)
#
# 두 머신은 같은 ROS_DOMAIN_ID 로 통신. ROS_DOMAIN_ID 환경변수는 양쪽 셸에서 일치하게.
#
# 동작:
#   - tmux 세션 'gogoping-pi' 안에 window 1개 (bringup) — camera/camera-pan 은 노트북 이동
#   - bringup    : gogoping_bringup pi.launch.py
#                  (모터 + sllidar_c1 + URDF + laser_filter, 모두 '/gogoping' namespace 안)
#   - 하단 status bar 의 window 이름 클릭으로 전환
#
# graph-router / gogoping_modes / camera (D435 + WebRTC) / camera-pan 은 laptop 측에서 띄움 —
# device-gogoping-laptop.sh.
#
# 사용:
#   scripts/device-gogoping-pi.sh           # 세션 시작·attach (이미 떠있으면 attach)
#   scripts/device-gogoping-pi.sh down      # tmux 세션 종료
#   scripts/device-gogoping-pi.sh status    # 세션 상태 + window 목록
#
# 의존:
#   - tmux
#   - /opt/ros/jazzy 설치
#   - repo root 에서 colcon build 완료 (./install/setup.bash 존재)
#   - ROS_DOMAIN_ID 는 호출 셸 환경 그대로 사용 (export 안 함)
#
# 환경변수:
#   ROS_DOMAIN_ID  laptop 과 일치 (호출 셸에서 export)
#
# 단축키 (tmux):
#   - 마우스로 하단 status bar 의 window 이름 클릭 → 전환
#   - Ctrl+B 다음 0/1 → window 번호로 전환
#   - Ctrl+B 다음 D → detach (백그라운드 유지)
set -euo pipefail

SESSION="gogoping-pi"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-up}"

ROS_SETUP="/opt/ros/jazzy/setup.zsh"
WS_SETUP="$REPO_ROOT/install/local_setup.zsh"

if ! command -v tmux &>/dev/null; then
  echo "[device-gogoping-pi] tmux 가 설치되어 있지 않습니다 (sudo apt install tmux)" >&2
  exit 1
fi

case "$ACTION" in
  up|"")
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[device-gogoping-pi] 세션 '$SESSION' 이미 떠있음 — attach"
      exec tmux attach -t "$SESSION"
    fi

    if [[ ! -f "$ROS_SETUP" ]]; then
      echo "[device-gogoping-pi] ROS Jazzy 가 설치되어 있지 않습니다 ($ROS_SETUP 없음)" >&2
      exit 1
    fi
    if [[ ! -f "$WS_SETUP" ]]; then
      echo "[device-gogoping-pi] workspace 가 빌드되어 있지 않습니다." >&2
      echo "[device-gogoping-pi]   cd $REPO_ROOT && colcon build --symlink-install" >&2
      exit 1
    fi

    # DDS discovery 는 ~/.zshrc 의 RMW_IMPLEMENTATION + CYCLONEDDS_URI (cyclonedds peers)
    # 로 처리한다. multicast 차단 환경에선 zshrc 의 <Peers> 안 IP 가 unicast 발견 담당.

    SOURCE_ENV="source $ROS_SETUP && source $WS_SETUP"

    # tmux 3.4 의 server idle 종료를 피하기 위해 첫 session 을 sleep 으로 띄우고
    # remain-on-exit 적용 후 실제 명령으로 respawn 한다.
    # remain-on-exit on: 프로세스 종료해도 window 유지 (에러 보고 디버깅 가능)
    tmux new-session -d -s "$SESSION" -x 200 -y 50 -n bringup -c "$REPO_ROOT" "sleep infinity"
    tmux set-option -t "$SESSION" -g remain-on-exit on
    tmux respawn-pane -k -t "$SESSION:bringup" -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_bringup pi.launch.py"

    # graph-router / gogoping_modes / camera (D435 + WebRTC) / camera-pan 은 laptop 측
    # (scripts/device-gogoping-laptop.sh) 에서 띄움.

    # 마우스 + status bar 설정 (window 이름 클릭으로 전환 가능)
    tmux set-option -t "$SESSION" -g mouse on
    tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
    tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
    tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
    tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

    tmux select-window -t "$SESSION:bringup"

    echo "[device-gogoping-pi] 세션 '$SESSION' 시작 — attach"
    echo "[device-gogoping-pi] ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-<unset>}"
    echo "[device-gogoping-pi] window: bringup (단일)"
    echo "[device-gogoping-pi] graph-router / gogoping_modes / camera / camera-pan 은 노트북에서: scripts/device-gogoping-laptop.sh"
    exec tmux attach -t "$SESSION"
    ;;
  down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      tmux kill-session -t "$SESSION"
      echo "[device-gogoping-pi] 세션 '$SESSION' 종료"
    else
      echo "[device-gogoping-pi] 세션 '$SESSION' 없음"
    fi
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[device-gogoping-pi] '$SESSION' 실행 중"
      tmux list-windows -t "$SESSION"
    else
      echo "[device-gogoping-pi] '$SESSION' 없음"
    fi
    ;;
  *)
    echo "usage: $0 [up|down|status]" >&2
    exit 2
    ;;
esac
