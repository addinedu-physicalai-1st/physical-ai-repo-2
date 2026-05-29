#!/usr/bin/env bash
# scripts/device-eduping-d435.sh — EduPing D435 상시 세트 기동 (단일 opener).
#
#   up      realsense2_camera(유일 opener) + rgb/pointcloud/depth bridge + static TF
#           + 무궁화 perception. autostart 미설치 dev 머신용 수동 진입점. D435 감지 가드.
#           카메라/bridge 는 등원·하원·율동·무궁화·건강검진·뎁스뷰 모든 카메라 모드에 영상
#           공급. perception 의 YOLO 는 idle 이며, robot-web 가 무궁화에 진입할 때만 추론.
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

stage_up() {
  local rc=0; detect_d435 || rc=$?
  if [[ $rc -eq 1 ]]; then
    log "✗ D435 미연결 — 미기동. 연결 후 재실행." >&2; exit 1
  elif [[ $rc -eq 2 ]]; then
    log "⚠ D435 확인 도구 없음 — 검증 없이 진행." >&2
  else
    log "✓ D435 발견"
  fi
  [[ -z "$DEVICE_TOKEN" ]] && log "⚠ DEVICE_TOKEN 미설정 — 무궁화 얼굴 등록(recognize) 인증 실패할 수 있음 (영상/판정은 정상)." >&2
  require_env
  # ros2 launch 는 빈 'device_token:=' 를 거부 — 토큰 있을 때만 인자 추가 (없으면 launch 기본값 "").
  local token_arg=""
  [[ -n "$DEVICE_TOKEN" ]] && token_arg=" device_token:=$DEVICE_TOKEN"
  start_window d435 "bash -lc 'source $ROS_SETUP && source $WS_SETUP && \
    ros2 launch eduarm eduping_d435_base.launch.py \
      control_url:=$CONTROL_URL recognize_base_url:=$RECOGNIZE_BASE_URL \
      server_host:=$SERVER_HOST$token_arg'"
}

prompt_menu() {
  cat >&2 <<EOF
=== eduping-d435 메뉴 ===
  1) up     상시 세트 (camera + rgb/pointcloud/depth + 무궁화 perception)
  s) status / d) down / q) 종료
EOF
  local c; read -rp "선택 [1/s/d/q]: " c >&2; echo "$c"
}

[[ -z "$ACTION" ]] && ACTION=$(prompt_menu)

case "$ACTION" in
  1|up)   stage_up ;;
  d|down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      # graceful: realsense2_camera 등 launch 자식 노드가 orphan 으로 남아 D435 'device busy'
      # 를 유발하지 않도록 SIGINT 먼저 보낸 뒤 kill-session.
      for w in $(tmux list-windows -t "$SESSION" -F '#{window_index}' 2>/dev/null); do
        tmux send-keys -t "$SESSION:$w" C-c 2>/dev/null || true
      done
      sleep 3
      tmux kill-session -t "$SESSION" 2>/dev/null || true
      log "세션 종료 (graceful)"
    else log "세션 없음"; fi ;;
  s|status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then tmux list-windows -t "$SESSION"; else log "세션 없음"; fi ;;
  q|quit|"") log "취소" ;;
  *) echo "usage: $0 [up|down|status]" >&2; exit 2 ;;
esac
