#!/usr/bin/env bash
# scripts/device-eduping.sh — eduping 노트북에서 실행하는 OpenArm 실물/mock 드라이버 묶음.
#
# 동작:
#   - tmux 세션 'eduping-device' 안에 window 1개 (bringup)
#   - bringup : openarm_bringup openarm.launch.py
#               (ros2_control + joint_trajectory_controller + robot_state_publisher)
#   - 활성화된 controller 가 표준 trajectory 토픽을 구독 → 추후 Control Server eduping bridge
#     가 EE 목표를 IK 풀어 publish 하면 팔이 움직임.
#
# 사용:
#   scripts/device-eduping.sh                            # mock 모드 (CAN/하드웨어 없이) 시작·attach
#   scripts/device-eduping.sh down                       # 세션 종료
#   scripts/device-eduping.sh status                     # 세션 상태
#   HARDWARE_TYPE=real CAN_INTERFACE=can0 scripts/device-eduping.sh   # 실물
#   ARM_TYPE=v10 scripts/device-eduping.sh                # 다른 arm 타입 (기본: v10)
#
# 의존:
#   - tmux
#   - /opt/ros/jazzy 설치
#   - device/eduping_ws/ 에서 colcon build 완료 (install/setup.bash 존재)
#   - HARDWARE_TYPE=real 인 경우: PEAK CAN 드라이버 + can0 인터페이스 up
#   - 호출 셸의 ROS_DOMAIN_ID 그대로 사용 (export 안 함)
#
# 단축키 (tmux):
#   - 마우스로 하단 status bar 의 window 이름 클릭 → 전환
#   - Ctrl+B 다음 D → detach (백그라운드 유지)
set -euo pipefail

SESSION="eduping-device"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS_DIR="$REPO_ROOT/device/eduping_ws"
ACTION="${1:-up}"
HARDWARE_TYPE="${HARDWARE_TYPE:-mock}"   # mock | real | mujoco
ARM_TYPE="${ARM_TYPE:-v10}"
CAN_INTERFACE="${CAN_INTERFACE:-can0}"

ROS_SETUP="/opt/ros/jazzy/setup.bash"
WS_SETUP="$WS_DIR/install/setup.bash"

if ! command -v tmux &>/dev/null; then
  echo "[device-eduping] tmux 가 설치되어 있지 않습니다 (sudo apt install tmux)" >&2
  exit 1
fi

case "$ACTION" in
  up|"")
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[device-eduping] 세션 '$SESSION' 이미 떠있음 — attach"
      exec tmux attach -t "$SESSION"
    fi

    if [[ ! -f "$ROS_SETUP" ]]; then
      echo "[device-eduping] ROS Jazzy 가 설치되어 있지 않습니다 ($ROS_SETUP 없음)" >&2
      exit 1
    fi
    if [[ ! -f "$WS_SETUP" ]]; then
      echo "[device-eduping] colcon build 결과가 없습니다 ($WS_SETUP 없음)" >&2
      echo "[device-eduping]   cd $WS_DIR && source $ROS_SETUP && \\" >&2
      echo "[device-eduping]     rosdep install --from-paths src --ignore-src -r -y && \\" >&2
      echo "[device-eduping]     colcon build --symlink-install" >&2
      exit 1
    fi
    if [[ "$HARDWARE_TYPE" == "real" ]] && ! ip link show "$CAN_INTERFACE" &>/dev/null; then
      echo "[device-eduping] ⚠ CAN 인터페이스 $CAN_INTERFACE 없음 — PEAK 드라이버/연결 확인" >&2
      echo "[device-eduping]   sudo ip link set $CAN_INTERFACE up type can bitrate 1000000" >&2
      # bringup 자체는 띄워봄 — 디버깅 용이성
    fi

    BRINGUP_CMD="bash -lc 'source $ROS_SETUP && source $WS_SETUP && \
      ros2 launch openarm_bringup openarm.launch.py \
        arm_type:=$ARM_TYPE hardware_type:=$HARDWARE_TYPE can_interface:=$CAN_INTERFACE'"

    tmux new-session -d -s "$SESSION" -x 200 -y 50 -n bringup -c "$WS_DIR" "$BRINGUP_CMD"
    tmux set-option -t "$SESSION" -g remain-on-exit on
    tmux set-option -t "$SESSION" -g mouse on
    tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
    tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
    tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
    tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

    echo "[device-eduping] 세션 '$SESSION' 시작 — arm_type=$ARM_TYPE hardware_type=$HARDWARE_TYPE can_interface=$CAN_INTERFACE"
    echo "[device-eduping] /joint_states 토픽이 살아나면 sim twin / Control Server 가 구독 가능"
    exec tmux attach -t "$SESSION"
    ;;
  down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      tmux kill-session -t "$SESSION"
      echo "[device-eduping] 세션 '$SESSION' 종료"
    else
      echo "[device-eduping] 세션 '$SESSION' 없음"
    fi
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[device-eduping] '$SESSION' 실행 중 (arm_type=$ARM_TYPE hardware_type=$HARDWARE_TYPE can_interface=$CAN_INTERFACE)"
      tmux list-windows -t "$SESSION"
    else
      echo "[device-eduping] '$SESSION' 없음"
    fi
    ;;
  *)
    echo "usage: $0 [up|down|status]" >&2
    exit 2
    ;;
esac
