#!/usr/bin/env bash
# scripts/device-gogoping-pi.sh — GogoPing 라즈베리파이에서 실행하는 ROS 노드 묶음.
#
# 동작:
#   - tmux 세션 'gogoping-pi' 안에 window 3개 (bringup / camera-pan / camera-stream)
#   - bringup       : vic_pinky_namespaced gogoping_bringup.launch.py
#                     (모터 + sllidar_c1 + URDF + laser_filter, '/gogoping' namespace)
#   - camera-pan    : gogoping_camera_pan camera_pan.launch.py (Arduino 시리얼 카메라 팬)
#   - camera-stream : device/gogoping_stream_ws/scripts/run_camera.sh
#                     (USB 웹캠 UDP MJPEG 송출 → Control Server, SR-CAM-001)
#   - 한 화면엔 1개 window 만 표시. 하단 status bar 의 window 이름 클릭으로 전환
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
# 환경변수 (camera-stream window 에 영향):
#   CONTROL_SERVER_NAME  shared/machine_ips.json 의 hostname (기본 'tonyno')
#   CAMERA_BACKEND       v4l2 (기본) | cv2
#   기타 CAMERA_* 환경변수는 device/gogoping_stream_ws/scripts/run_camera.sh 참조
#
# 단축키 (tmux):
#   - 마우스로 하단 status bar 의 window 이름 클릭 → 전환
#   - Ctrl+B 다음 0/1/2 → window 번호로 전환
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

    SOURCE_ENV="source $ROS_SETUP && source $WS_SETUP"

    # tmux 3.4 의 server idle 종료를 피하기 위해 첫 session 을 sleep 으로 띄우고
    # remain-on-exit 적용 후 실제 명령으로 respawn 한다.
    # remain-on-exit on: 프로세스 종료해도 window 유지 (에러 보고 디버깅 가능)
    tmux new-session -d -s "$SESSION" -x 200 -y 50 -n bringup -c "$REPO_ROOT" "sleep infinity"
    tmux set-option -t "$SESSION" -g remain-on-exit on
    tmux respawn-pane -k -t "$SESSION:bringup" -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch vic_pinky_namespaced gogoping_bringup.launch.py"

    # window 1: camera-pan
    tmux new-window -t "$SESSION" -n camera-pan -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_camera_pan camera_pan.launch.py"

    # window 2: camera-stream — USB 웹캠 UDP MJPEG 송출 (Control Server 로)
    # ROS 의존 없음 (UDP 직접 송신). conda env / CAMERA_*/CONTROL_SERVER_NAME 은 호출 셸에서 상속.
    tmux new-window -t "$SESSION" -n camera-stream -c "$REPO_ROOT" \
      "exec env CAMERA_ROBOT=gogoping device/gogoping_stream_ws/scripts/run_camera.sh"

    # 마우스 + status bar 설정 (window 이름 클릭으로 전환 가능)
    tmux set-option -t "$SESSION" -g mouse on
    tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
    tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
    tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
    tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

    tmux select-window -t "$SESSION:bringup"

    echo "[device-gogoping-pi] 세션 '$SESSION' 시작 — attach"
    echo "[device-gogoping-pi] ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-<unset>}"
    echo "[device-gogoping-pi] CONTROL_SERVER_NAME=${CONTROL_SERVER_NAME:-tonyno (default)}"
    echo "[device-gogoping-pi] 하단 status bar 의 'bringup / camera-pan / camera-stream' 클릭으로 전환"
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
