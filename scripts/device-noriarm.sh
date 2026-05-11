#!/usr/bin/env bash
# scripts/device-noriarm.sh — NoriArm 노트북에서 실행하는 OMX-F 실물 드라이버 묶음.
#
# 동작:
#   - tmux 세션 'noriarm-device' 안에 window 1개 (bringup)
#   - bringup : open_manipulator_bringup omx_f.launch.py
#               (dynamixel_hardware_interface + arm_controller(JointTrajectoryController))
#   - 활성화된 controller 가 `/arm_controller/joint_trajectory` 를 구독 →
#     Control Server NoriarmRosBridge 가 거기에 publish 하면 실물 팔이 움직임 (SR-NORI-007 real path).
#
# 사용:
#   scripts/device-noriarm.sh                          # 시작·attach (이미 떠있으면 attach)
#   scripts/device-noriarm.sh down                     # 세션 종료
#   scripts/device-noriarm.sh status                   # 세션 상태
#   PORT=/dev/ttyUSB0 scripts/device-noriarm.sh        # 다른 포트로 (기본: /dev/omx_follower)
#   INIT_POSITION=true scripts/device-noriarm.sh       # 부팅 시 init→home 시퀀스 켜기 (기본: false)
#
# 의존:
#   - tmux
#   - /opt/ros/jazzy 설치
#   - device/noriarm_ws/ 에서 colcon build 완료 (install/setup.bash 존재)
#   - /dev/omx_follower (udev rule 또는 PORT env 로 override 가능)
#   - 호출 셸의 ROS_DOMAIN_ID 그대로 사용 (export 안 함)
#
# 단축키 (tmux):
#   - 마우스로 하단 status bar 의 window 이름 클릭 → 전환
#   - Ctrl+B 다음 D → detach (백그라운드 유지)
set -euo pipefail

SESSION="noriarm-device"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS_DIR="$REPO_ROOT/device/noriarm_ws"
ACTION="${1:-up}"
PORT="${PORT:-/dev/omx_follower}"
# bringup 부팅 시 자동 init→home 시퀀스 (initial_positions.yaml 의 step1→step2).
# 기본 false — 매 답마다 trajectory 가 안전 자세부터 풀로 보내져서 굳이 미리 정렬할
# 필요 없고, 부팅 5초 지연 + 모터 토크로 책상 위 물건 칠 위험 회피.
INIT_POSITION="${INIT_POSITION:-false}"

ROS_SETUP="/opt/ros/jazzy/setup.bash"
WS_SETUP="$WS_DIR/install/setup.bash"

if ! command -v tmux &>/dev/null; then
  echo "[device-noriarm] tmux 가 설치되어 있지 않습니다 (sudo apt install tmux)" >&2
  exit 1
fi

case "$ACTION" in
  up|"")
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[device-noriarm] 세션 '$SESSION' 이미 떠있음 — attach"
      exec tmux attach -t "$SESSION"
    fi

    if [[ ! -f "$ROS_SETUP" ]]; then
      echo "[device-noriarm] ROS Jazzy 가 설치되어 있지 않습니다 ($ROS_SETUP 없음)" >&2
      exit 1
    fi
    if [[ ! -f "$WS_SETUP" ]]; then
      echo "[device-noriarm] colcon build 결과가 없습니다 ($WS_SETUP 없음)" >&2
      echo "[device-noriarm]   cd $WS_DIR && source $ROS_SETUP && colcon build --symlink-install" >&2
      exit 1
    fi
    if [[ ! -e "$PORT" ]]; then
      echo "[device-noriarm] ⚠ $PORT 디바이스가 없음 — udev rule 또는 USB 연결 확인" >&2
      echo "[device-noriarm]   ls -la /dev/serial/by-id/ 로 실제 시리얼 ID 확인 가능" >&2
      # bringup 자체는 띄워봄 — 사용자가 디버깅하기 쉽도록
    fi

    BRINGUP_CMD="bash -lc 'source $ROS_SETUP && source $WS_SETUP && \
      ros2 launch open_manipulator_bringup omx_f.launch.py \
        port_name:=$PORT init_position:=$INIT_POSITION'"

    tmux new-session -d -s "$SESSION" -x 200 -y 50 -n bringup -c "$WS_DIR" "$BRINGUP_CMD"
    tmux set-option -t "$SESSION" -g remain-on-exit on
    tmux set-option -t "$SESSION" -g mouse on
    tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
    tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
    tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
    tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

    echo "[device-noriarm] 세션 '$SESSION' 시작 — port=$PORT init_position=$INIT_POSITION"
    echo "[device-noriarm] /arm_controller/joint_trajectory 토픽이 살아나면 Control Server 가 publish 가능"
    exec tmux attach -t "$SESSION"
    ;;
  down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      tmux kill-session -t "$SESSION"
      echo "[device-noriarm] 세션 '$SESSION' 종료"
    else
      echo "[device-noriarm] 세션 '$SESSION' 없음"
    fi
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[device-noriarm] '$SESSION' 실행 중 (port=$PORT init_position=$INIT_POSITION)"
      tmux list-windows -t "$SESSION"
    else
      echo "[device-noriarm] '$SESSION' 없음"
    fi
    ;;
  *)
    echo "usage: $0 [up|down|status]" >&2
    exit 2
    ;;
esac
