#!/usr/bin/env bash
# scripts/device-eduping-leader.sh — 실물 openarm_mini (Feetech 양팔 leader) 띄움.
#
# 인터랙티브 메뉴 (인자 없을 때 자동 표시) — 또는 인자로 0/1/2/3/down/status 직접 지정:
#
#   0 (setup)     모터 등록 — lerobot-setup-motors (서보 ID/baud EEPROM 기록, 1회)
#   1 (check)     모터 점검만 — 양팔 8 모터 ping
#   2 (calibrate) calibration JSON 존재 확인 + 없으면 lerobot 안내
#   3 (up)        전체: 1 → 2 → bringup (tmux 세션 시작)
#   down          세션 종료
#   status        세션 상태
#
# 사용:
#   scripts/device-eduping-leader.sh             # 인터랙티브 메뉴
#   scripts/device-eduping-leader.sh 1           # 모터 점검만
#   scripts/device-eduping-leader.sh 3           # bringup (전체 흐름)
#   scripts/device-eduping-leader.sh down
#
#   PORT_RIGHT=/dev/ttyACM0 PORT_LEFT=/dev/ttyACM1 \
#     scripts/device-eduping-leader.sh           # symlink 없을 때
#
# 의존:
#   - tmux, /opt/ros/jazzy, controller/eduping-controller/ 빌드 완료
#   - conda env 'pdg' 활성화 (feetech-servo-sdk 가 거기 있음). 미활성이면 안내 후 중단.
#   - lerobot calibration JSON: ~/.cache/huggingface/lerobot/calibration/teleoperators/openarm_mini/my_mini_leader_arm.json
#   - udev 심볼릭 (권장): /dev/op_mini_right, /dev/op_mini_left
set -euo pipefail

SESSION="eduping-leader"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WS_DIR="$REPO_ROOT/controller/eduping-controller"
ACTION="${1:-}"
PORT_RIGHT="${PORT_RIGHT:-/dev/op_mini_right}"
PORT_LEFT="${PORT_LEFT:-/dev/op_mini_left}"
BAUDRATE="${BAUDRATE:-1000000}"
RATE_HZ="${RATE_HZ:-50.0}"
CALIBRATION_PATH="${CALIBRATION_PATH:-$HOME/.cache/huggingface/lerobot/calibration/teleoperators/openarm_mini/my_mini_leader_arm.json}"
CALIBRATION_ID="${CALIBRATION_ID:-my_mini_leader_arm}"

ROS_SETUP="/opt/ros/jazzy/setup.bash"
# colcon install 위치: 루트(repo-wide) 우선, 없으면 controller/eduping-controller/install 로 폴백.
ROOT_SETUP="$REPO_ROOT/install/setup.bash"
WS_SETUP_FALLBACK="$WS_DIR/install/setup.bash"
WS_SETUP=""

log() { echo "[device-eduping-leader] $*"; }

if ! command -v tmux &>/dev/null; then
  log "tmux 가 설치되어 있지 않습니다 (sudo apt install tmux)" >&2
  exit 1
fi

# --- 환경 / conda env 확인 ----------------------------------------------
require_env() {
  if [[ ! -f "$ROS_SETUP" ]]; then
    log "ROS Jazzy 가 설치되어 있지 않습니다 ($ROS_SETUP 없음)" >&2
    exit 1
  fi
  if [[ -f "$ROOT_SETUP" ]]; then
    WS_SETUP="$ROOT_SETUP"
  elif [[ -f "$WS_SETUP_FALLBACK" ]]; then
    WS_SETUP="$WS_SETUP_FALLBACK"
  else
    log "colcon build 결과가 없습니다" >&2
    log "  탐색 경로:" >&2
    log "    1) $ROOT_SETUP" >&2
    log "    2) $WS_SETUP_FALLBACK" >&2
    log "  루트 또는 controller/eduping-controller/ 에서 빌드 후 재실행." >&2
    exit 1
  fi
  if [[ "${CONDA_DEFAULT_ENV:-}" != "pdg" ]]; then
    log "⚠ conda 'pdg' env 가 활성화 안 됨 (현재: ${CONDA_DEFAULT_ENV:-none})" >&2
    log "  'conda activate pdg' 후 재실행. (feetech-servo-sdk 가 pdg 에만 설치돼 있음)" >&2
    exit 1
  fi
}

# --- 1. 모터 점검 (python -m 으로 호출 — 시스템 python 대신 가상환경 사용) ---
stage_check() {
  log "[1] 모터 점검 (양팔 × 8 ping)"
  for P in "$PORT_RIGHT" "$PORT_LEFT"; do
    if [[ ! -e "$P" ]]; then
      log "  ⚠ 포트 $P 없음 — USB 연결/심볼릭/권한 확인" >&2
      log "    ls -l /dev/ttyACM* /dev/op_mini_*  ;  sudo usermod -aG dialout \$USER" >&2
    fi
  done

  bash -c "source $ROS_SETUP && source $WS_SETUP && \
    python -m eduarm.feetech_leader_node --ros-args \
      -p port_right:=$PORT_RIGHT \
      -p port_left:=$PORT_LEFT \
      -p baudrate:=$BAUDRATE \
      -p calibration_path:=$CALIBRATION_PATH \
      -p check_only:=true"
}

# --- 0. Motor setup (lerobot-setup-motors) -------------------------------
# 서보 EEPROM 에 모터 ID/baudrate 를 기록. 다른 컴퓨터/로봇에서 쓰던 서보거나 baud 가
# 안 맞아 모터가 enumerate 안 될 때 1회 실행 (calibration 전에). 화면 안내 따라 진행.
stage_setup_motors() {
  log "[0] 모터 등록 (lerobot-setup-motors — 양팔 ID/baud EEPROM 기록)"
  if ! command -v lerobot-setup-motors &>/dev/null; then
    log "  ✗ lerobot-setup-motors 명령 없음 — 현재 env 에 lerobot 미설치" >&2
    log "    같은 env (pdg) 에 lerobot 설치 후 재실행." >&2
    return 1
  fi
  for P in "$PORT_RIGHT" "$PORT_LEFT"; do
    if [[ ! -e "$P" ]]; then
      log "  ⚠ 포트 $P 없음 — USB 연결/심볼릭/권한 확인" >&2
      log "    ls -l /dev/ttyACM* /dev/op_mini_*  ;  sudo usermod -aG dialout \$USER" >&2
    fi
  done
  log "  화면 안내 따라 모터를 하나씩 등록하세요 (전원 + USB 연결 상태)."
  lerobot-setup-motors \
    --teleop.type=openarm_mini \
    --teleop.port_right="$PORT_RIGHT" \
    --teleop.port_left="$PORT_LEFT" \
    || { log "  ✗ lerobot-setup-motors 실패 — 전원·결선·baud 확인" >&2; return 1; }
  log "  ✓ 모터 등록 완료 — 이제 메뉴 2 (calibration) 진행"
}

# --- 2. Calibration ------------------------------------------------------
# JSON 있으면 "다시 하시겠습니까?" 묻고 NO 면 그대로 통과, YES 면 lerobot-calibrate 실행.
# JSON 없으면 바로 실행. lerobot-calibrate 가 같은 env (pdg) 에 설치돼있어야 함.
stage_calibrate() {
  log "[2] calibration JSON 확인 — $CALIBRATION_PATH"

  local do_run=0
  if [[ -f "$CALIBRATION_PATH" ]]; then
    log "  ✓ 이미 존재"
    local answer
    read -rp "  캘리브레이션을 다시 하시겠습니까? [y/N]: " answer >&2
    case "$answer" in
      y|Y|yes|YES) do_run=1 ;;
      *)           log "  → 기존 JSON 그대로 사용"; return 0 ;;
    esac
  else
    log "  ✗ calibration JSON 없음 — 새로 생성합니다"
    do_run=1
  fi

  if [[ "$do_run" -eq 1 ]]; then
    if ! command -v lerobot-calibrate &>/dev/null; then
      log "  ✗ lerobot-calibrate 명령 없음 — 현재 env 에 lerobot 미설치" >&2
      log "    같은 env (pdg) 에 lerobot 설치 후 재실행:" >&2
      log "    pip install lerobot   (또는 lerobot 저장소에서 -e 설치)" >&2
      return 1
    fi
    log "  lerobot-calibrate 실행 — 화면 안내 따라 양팔 각 조인트를 끝점까지 움직이세요"
    lerobot-calibrate \
      --teleop.type=openarm_mini \
      --teleop.port_right="$PORT_RIGHT" \
      --teleop.port_left="$PORT_LEFT" \
      --teleop.id="$CALIBRATION_ID" \
      || { log "  ✗ lerobot-calibrate 실패" >&2; return 1; }

    if [[ ! -f "$CALIBRATION_PATH" ]]; then
      log "  ⚠ 완료 후 JSON 이 예상 경로에 없음: $CALIBRATION_PATH" >&2
      log "    lerobot 의 기본 저장 위치가 다를 수 있음 — 찾아서 CALIBRATION_PATH 로 지정." >&2
      return 1
    fi
    log "  ✓ JSON 생성/갱신 완료"
  fi
}

# --- 3. Bringup (tmux) ---------------------------------------------------
stage_bringup() {
  log "[3] bringup — tmux 세션 '$SESSION' 시작"

  LEADER_CMD="bash -lc 'source $ROS_SETUP && source $WS_SETUP && \
    python -m eduarm.feetech_leader_node --ros-args \
      -p port_right:=$PORT_RIGHT \
      -p port_left:=$PORT_LEFT \
      -p baudrate:=$BAUDRATE \
      -p rate_hz:=$RATE_HZ \
      -p calibration_path:=$CALIBRATION_PATH'"

  tmux new-session -d -s "$SESSION" -x 200 -y 50 -n leader -c "$WS_DIR" "$LEADER_CMD"
  tmux set-option -t "$SESSION" -g remain-on-exit on
  tmux set-option -t "$SESSION" -g mouse on
  tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
  tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
  tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
  tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

  log "right=$PORT_RIGHT left=$PORT_LEFT baud=$BAUDRATE rate=${RATE_HZ}Hz"
  log "/eduping/leader/joint_states 16 joint publish — Control Server bridge 가 구독"
  exec tmux attach -t "$SESSION"
}

# --- 인터랙티브 메뉴 -----------------------------------------------------
prompt_menu() {
  cat >&2 <<EOF
=== eduping-leader 메뉴 ===
  0) 모터 등록          (lerobot-setup-motors — ID/baud, 1회/모터 교체 시)
  1) 모터 점검만        (양팔 16 모터 ping)
  2) calibration       (JSON 새로 만들기 / 다시 만들기)
  3) bringup 시작       (모터 점검 → tmux 세션 시작; calibration JSON 만 확인)
  s) status / d) down
  q) 종료
EOF
  local choice
  read -rp "선택 [0/1/2/3/s/d/q]: " choice >&2
  echo "$choice"
}

if [[ -z "$ACTION" ]]; then
  ACTION=$(prompt_menu)
fi

case "$ACTION" in
  0|setup|motors)
    require_env
    stage_setup_motors
    ;;
  1|check)
    require_env
    stage_check
    ;;
  2|cal|calibrate)
    stage_calibrate
    ;;
  3|up|"")
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      log "세션 '$SESSION' 이미 떠있음 — attach"
      exec tmux attach -t "$SESSION"
    fi
    require_env
    if [[ "${SKIP_CHECK:-0}" != "1" ]]; then
      stage_check || { log "✗ 모터 점검 실패 — bringup 중단" >&2; exit 1; }
    else
      log "[1] (SKIP_CHECK=1 — 모터 점검 우회)"
    fi
    if [[ ! -f "$CALIBRATION_PATH" ]]; then
      log "✗ calibration JSON 없음: $CALIBRATION_PATH" >&2
      log "  먼저 메뉴 2 (calibration) 으로 JSON 생성." >&2
      exit 1
    fi
    stage_bringup
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
      log "'$SESSION' 실행 중 (right=$PORT_RIGHT left=$PORT_LEFT)"
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
    echo "usage: $0 [0|1|2|3|setup|check|calibrate|up|down|status]" >&2
    exit 2
    ;;
esac
