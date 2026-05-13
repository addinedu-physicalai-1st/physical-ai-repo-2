#!/usr/bin/env bash
# scripts/device-eduping.sh — OpenArm 양팔 follower bringup (mock / real).
#
# 인터랙티브 메뉴 (인자 없을 때 자동 표시) — 또는 인자로 1/2/3/down/status 직접:
#
#   1 (mock)         openarm_bringup mock 모드 (CAN/하드웨어 없이 토픽만)
#   2 (check)        실물 follower 16 모터 preflight 만 (openarm-can-motor-check)
#   3 (real)         실물 bringup (모터 preflight 통과 후 openarm_bringup hardware_type=real)
#   down             세션 종료
#   status           세션 상태
#
# 사용:
#   scripts/device-eduping.sh             # 인터랙티브 메뉴
#   scripts/device-eduping.sh 1           # mock 바로
#   scripts/device-eduping.sh 3           # real bringup (check + bringup)
#   scripts/device-eduping.sh down
#
#   RIGHT_CAN=can0 LEFT_CAN=can1 ARM_TYPE=v10 scripts/device-eduping.sh 3
#   SKIP_MOTOR_CHECK=1 scripts/device-eduping.sh 3                 # preflight 우회
#
# 의존:
#   - tmux, /opt/ros/jazzy, device/eduping_ws/ 빌드 완료
#   - 실물 (real) : PEAK CAN 드라이버 + can0(right)/can1(left) up + openarm-can-motor-check
#   - 호출 셸의 ROS_DOMAIN_ID 그대로 사용
set -euo pipefail

SESSION="eduping-device"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS_DIR="$REPO_ROOT/device/eduping_ws"
ACTION="${1:-}"
ARM_TYPE="${ARM_TYPE:-v10}"
RIGHT_CAN="${RIGHT_CAN:-can0}"
LEFT_CAN="${LEFT_CAN:-can1}"

ROS_SETUP="/opt/ros/jazzy/setup.bash"
WS_SETUP="$WS_DIR/install/setup.bash"

log() { echo "[device-eduping] $*"; }

if ! command -v tmux &>/dev/null; then
  log "tmux 가 설치되어 있지 않습니다 (sudo apt install tmux)" >&2
  exit 1
fi

require_env() {
  if [[ ! -f "$ROS_SETUP" ]]; then
    log "ROS Jazzy 가 설치되어 있지 않습니다 ($ROS_SETUP 없음)" >&2
    exit 1
  fi
  if [[ ! -f "$WS_SETUP" ]]; then
    log "colcon build 결과가 없습니다 ($WS_SETUP 없음)" >&2
    log "  device/eduping_ws/ 에서 빌드 후 재실행." >&2
    exit 1
  fi
}

# --- CAN 인터페이스 존재 확인 (real 모드만 의미) -------------------------
check_can_interfaces() {
  for IF in "$RIGHT_CAN" "$LEFT_CAN"; do
    if ! ip link show "$IF" &>/dev/null; then
      log "⚠ CAN 인터페이스 $IF 없음 — PEAK 드라이버/연결 확인" >&2
      log "  sudo ip link set $IF up type can bitrate 1000000" >&2
    fi
  done
}

# --- follower 16 모터 (양팔 × 8) preflight ------------------------------
stage_motor_check() {
  log "[check] follower 모터 점검 (양팔 16개)"
  if ! command -v openarm-can-motor-check &>/dev/null; then
    log "  ✗ openarm-can-motor-check 명령 없음 — openarm_can 빌드/설치 확인" >&2
    return 1
  fi

  FAILED=()
  for CAN_PAIR in "right:$RIGHT_CAN" "left:$LEFT_CAN"; do
    SIDE="${CAN_PAIR%%:*}"
    IFACE="${CAN_PAIR##*:}"
    for i in 1 2 3 4 5 6 7 8; do
      RECV=$((i + 16))
      OUT=$(openarm-can-motor-check "$i" "$RECV" "$IFACE" -fd 2>&1)
      if echo "$OUT" | grep -qE '^(Error:|Failed)'; then
        echo "  ✗ $SIDE id=$i/$RECV ($IFACE) — 응답 없음"
        FAILED+=("$SIDE/$i")
      else
        echo "  ✓ $SIDE id=$i/$RECV ($IFACE)"
      fi
    done
  done
  if [[ ${#FAILED[@]} -gt 0 ]]; then
    log "✗ ${#FAILED[@]}/16 모터 응답 없음: ${FAILED[*]}" >&2
    log "  전원·CAN 결선·motor ID 확인. 우회: SKIP_MOTOR_CHECK=1" >&2
    return 1
  fi
  log "✓ 16/16 모터 OK"
}

# --- bringup tmux 띄움 (mock 또는 real) ---------------------------------
stage_bringup() {
  local HARDWARE_TYPE="$1"  # mock | real

  if tmux has-session -t "$SESSION" 2>/dev/null; then
    log "세션 '$SESSION' 이미 떠있음 — attach"
    exec tmux attach -t "$SESSION"
  fi
  require_env

  if [[ "$HARDWARE_TYPE" == "real" ]]; then
    check_can_interfaces
    if [[ "${SKIP_MOTOR_CHECK:-0}" != "1" ]]; then
      stage_motor_check || { log "✗ 모터 점검 실패 — bringup 중단" >&2; exit 1; }
    else
      log "[check] (SKIP_MOTOR_CHECK=1 — 우회)"
    fi
  fi

  BRINGUP_CMD="bash -lc 'source $ROS_SETUP && source $WS_SETUP && \
    ros2 launch openarm_bringup openarm.bimanual.launch.py \
      arm_type:=$ARM_TYPE hardware_type:=$HARDWARE_TYPE \
      right_can_interface:=$RIGHT_CAN left_can_interface:=$LEFT_CAN'"

  tmux new-session -d -s "$SESSION" -x 200 -y 50 -n bringup -c "$WS_DIR" "$BRINGUP_CMD"
  tmux set-option -t "$SESSION" -g remain-on-exit on
  tmux set-option -t "$SESSION" -g mouse on
  tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
  tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
  tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
  tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

  log "세션 '$SESSION' 시작 — arm_type=$ARM_TYPE hardware_type=$HARDWARE_TYPE right=$RIGHT_CAN left=$LEFT_CAN"
  log "/joint_states 토픽이 살아나면 sim twin / Control Server 가 구독 가능"
  exec tmux attach -t "$SESSION"
}

# --- 인터랙티브 메뉴 -----------------------------------------------------
prompt_menu() {
  cat >&2 <<EOF
=== eduping-device 메뉴 ===
  1) mock bringup        (하드웨어 없이 토픽만)
  2) follower 모터 점검   (real 시 16 모터 ping, bringup 안 함)
  3) real bringup        (모터 점검 → 실물 hardware_type=real)
  s) status / d) down
  q) 종료
EOF
  local choice
  read -rp "선택 [1/2/3/s/d/q]: " choice >&2
  echo "$choice"
}

if [[ -z "$ACTION" ]]; then
  ACTION=$(prompt_menu)
fi

case "$ACTION" in
  1|mock)
    stage_bringup "mock"
    ;;
  2|check)
    require_env
    check_can_interfaces
    stage_motor_check
    ;;
  3|real|up)
    stage_bringup "real"
    ;;
  d|down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      tmux kill-session -t "$SESSION"
      log "세션 '$SESSION' 종료"
    else
      log "세션 '$SESSION' 없음"
    fi
    ;;
  s|status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      log "'$SESSION' 실행 중 (arm_type=$ARM_TYPE right=$RIGHT_CAN left=$LEFT_CAN)"
      tmux list-windows -t "$SESSION"
    else
      log "'$SESSION' 없음"
    fi
    ;;
  q|quit|"")
    log "취소"
    ;;
  *)
    echo "알 수 없는 선택: $ACTION" >&2
    echo "usage: $0 [1|2|3|mock|check|real|down|status]" >&2
    exit 2
    ;;
esac
