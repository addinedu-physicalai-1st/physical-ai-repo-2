#!/usr/bin/env bash
# scripts/device-eduping-d435.sh — EduPing D435 단일 opener 기동.
#
#   base    상시 세트 (realsense2_camera + rgb/pointcloud/depth bridge + static TF).
#           autostart 미설치 dev 머신용 수동 진입점. D435 감지 가드.
#   game    무궁화 perception 만 (이미 떠있는 /d435/color/image_raw 구독).
#   down / status
#
#   CONTROL_URL / RECOGNIZE_BASE_URL / DEVICE_TOKEN / SERVER_HOST env override.
set -euo pipefail

SESSION="eduping-d435"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS_DIR="$REPO_ROOT/controller/eduping-controller"
ACTION="${1:-}"

CONTROL_URL="${CONTROL_URL:-ws://localhost:8000}"
RECOGNIZE_BASE_URL="${RECOGNIZE_BASE_URL:-http://localhost:8000}"
DEVICE_TOKEN="${DEVICE_TOKEN:-}"
SERVER_HOST="${SERVER_HOST:-127.0.0.1}"

ROS_SETUP="/opt/ros/jazzy/setup.bash"
ROOT_SETUP="$REPO_ROOT/install/setup.bash"
WS_SETUP_FALLBACK="$WS_DIR/install/setup.bash"
WS_SETUP=""

log() { echo "[device-d435] $*"; }

command -v tmux &>/dev/null || { log "tmux 필요 (sudo apt install tmux)" >&2; exit 1; }

require_env() {
  [[ -f "$ROS_SETUP" ]] || { log "ROS Jazzy 없음 ($ROS_SETUP)" >&2; exit 1; }
  if [[ -f "$ROOT_SETUP" ]]; then WS_SETUP="$ROOT_SETUP"
  elif [[ -f "$WS_SETUP_FALLBACK" ]]; then WS_SETUP="$WS_SETUP_FALLBACK"
  else log "colcon build 결과 없음 ($ROOT_SETUP / $WS_SETUP_FALLBACK)" >&2; exit 1; fi
}

# 0=발견 1=없음 2=확인불가
detect_d435() {
  if command -v rs-enumerate-devices &>/dev/null; then
    rs-enumerate-devices -s 2>/dev/null | grep -qiE "intel realsense|D4[0-9][0-9]" && return 0
    return 1
  fi
  if command -v lsusb &>/dev/null; then
    lsusb 2>/dev/null | grep -qiE "realsense|8086:0b" && return 0
    return 1
  fi
  return 2
}

start_window() {  # $1=name $2=cmd
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    if tmux list-windows -t "$SESSION" -F '#{window_name}' | grep -qx "$1"; then
      log "윈도 '$1' 이미 있음 — attach"; exec tmux attach -t "$SESSION"
    fi
    tmux new-window -t "$SESSION" -n "$1" -c "$WS_DIR" "$2"
  else
    tmux new-session -d -s "$SESSION" -x 200 -y 50 -n "$1" -c "$WS_DIR" "$2"
    tmux set-option -t "$SESSION" -g remain-on-exit on
    tmux set-option -t "$SESSION" -g mouse on
  fi
  log "세션 '$SESSION' 윈도 '$1' 기동"
  exec tmux attach -t "$SESSION"
}

stage_base() {
  local rc=0; detect_d435 || rc=$?
  if [[ $rc -eq 1 ]]; then
    log "✗ D435 미연결 — base 미기동. 연결 후 재실행." >&2; exit 1
  elif [[ $rc -eq 2 ]]; then
    log "⚠ D435 확인 도구 없음 — 검증 없이 진행." >&2
  else
    log "✓ D435 발견"
  fi
  require_env
  start_window base "bash -lc 'source $ROS_SETUP && source $WS_SETUP && \
    ros2 launch eduarm eduping_d435_base.launch.py \
      control_url:=$CONTROL_URL server_host:=$SERVER_HOST'"
}

stage_game() {
  require_env
  [[ -z "$DEVICE_TOKEN" ]] && log "⚠ DEVICE_TOKEN 미설정 — 얼굴 등록(recognize) 인증 실패할 수 있음." >&2
  start_window game "bash -lc 'source $ROS_SETUP && source $WS_SETUP && \
    ros2 launch eduarm mugunghwa.launch.py \
      control_url:=$CONTROL_URL recognize_base_url:=$RECOGNIZE_BASE_URL device_token:=$DEVICE_TOKEN'"
}

prompt_menu() {
  cat >&2 <<EOF
=== eduping-d435 메뉴 ===
  1) base   상시 세트 (camera + rgb/pointcloud/depth)
  2) game   무궁화 perception (base 떠있어야 함)
  s) status / d) down / q) 종료
EOF
  local c; read -rp "선택 [1/2/s/d/q]: " c >&2; echo "$c"
}

[[ -z "$ACTION" ]] && ACTION=$(prompt_menu)

case "$ACTION" in
  1|base)   stage_base ;;
  2|game)   stage_game ;;
  d|down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then tmux kill-session -t "$SESSION"; log "세션 종료";
    else log "세션 없음"; fi ;;
  s|status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then tmux list-windows -t "$SESSION"; else log "세션 없음"; fi ;;
  q|quit|"") log "취소" ;;
  *) echo "usage: $0 [1|2|base|game|down|status]" >&2; exit 2 ;;
esac
