#!/usr/bin/env bash
# scripts/device-eduping.sh — OpenArm 양팔 follower bringup (실물 전용).
# bringup(real) 시 같은 tmux 세션에 윈도 3개를 띄운다: 'bringup'(팔) + 'd435'(카메라 상시
# 세트 = eduping_d435_base.launch.py) + 'stetho'(청진기 FSR 브리지). d435/stetho 는 팔과
# 독립된 별도 윈도라 CAN/모터 실패와 무관하게 카메라/perception/청진기가 뜬다.
# (청진기 = eduping 노트북에 물린 하드웨어 → doctor teleop 이 아닌 device 세트에 둠.)
#
# 인터랙티브 메뉴 (인자 없을 때 자동 표시) — 또는 인자로 직접:
#
#   0 (setup)        CAN-FD 인터페이스 설정 (lerobot-setup-can --mode=setup, 부팅 후 1회)
#   1 (check)        통신 & 모터 점검 (lerobot-setup-can --mode=test, 양팔 ping)
#   2 (calibrate)    lerobot openarm_follower 양팔 캘리브레이션 (CAN 인터페이스별 1회 셋업)
#   3 (real)         실물 bringup (preflight 없이 바로 openarm_bringup hardware_type=real)
#   down             세션 종료
#   status           세션 상태
#
# 사용:
#   scripts/device-eduping.sh             # 인터랙티브 메뉴
#   scripts/device-eduping.sh 3           # real bringup (control 서버는 TTY 면 메뉴로 선택)
#   scripts/device-eduping.sh 3 hajuntu  # control 서버 = 등록된 머신(의사 머신) IP
#   scripts/device-eduping.sh 3 192.168.0.152   # control 서버 = IP 직접
#   scripts/device-eduping.sh 3 local     # control 서버 = localhost
#   CONTROL=hajuntu scripts/device-eduping.sh 3
#   scripts/device-eduping.sh down
#
#   RIGHT_CAN=can0 LEFT_CAN=can1 ARM_TYPE=v10 scripts/device-eduping.sh 3
#
# control 서버 선택 (2-머신: eduping → 의사 머신 control):
#   2번째 인자 또는 CONTROL env = 머신이름(shared/machine_ips.json) | IP | local.
#   d435 uploader(ws://:8000) + recognize(http://:8000) + depth streamer(:8100) host 를 한 번에 맞춤.
#   CONTROL_URL 을 직접 export 하면 그게 최우선(기존 동작 유지). 미지정+TTY 면 메뉴.
#
# 의존:
#   - tmux, /opt/ros/jazzy, controller/eduping-controller/ 빌드 완료
#   - PEAK CAN 드라이버 + can0(right)/can1(left) up
#   - 같은 env (pdg) 에 lerobot 설치
#   - 호출 셸의 ROS_DOMAIN_ID 그대로 사용
set -euo pipefail

SESSION="eduping-device"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WS_DIR="$REPO_ROOT/controller/eduping-controller"
source "$SCRIPT_DIR/_run_lib.sh"   # _runlib::resolve_control_token / choose_control_host
ACTION="${1:-}"
CONTROL_ARG="${2:-}"               # control 서버 선택: 머신이름(machine_ips.json)|IP|local
ARM_TYPE="${ARM_TYPE:-v10}"
RIGHT_CAN="${RIGHT_CAN:-can0}"
LEFT_CAN="${LEFT_CAN:-can1}"
CALIBRATION_ID="${CALIBRATION_ID:-my_openarm_follower}"

ROS_SETUP="/opt/ros/jazzy/setup.bash"
# colcon install 위치: 루트(repo-wide) 우선, 없으면 controller/eduping-controller/install 로 폴백.
ROOT_SETUP="$REPO_ROOT/install/setup.bash"
WS_SETUP_FALLBACK="$WS_DIR/install/setup.bash"
WS_SETUP=""

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

# --- lerobot openarm_follower 양팔 calibration --------------------------
# 양팔 각각 별도 실행 (CAN 인터페이스가 분리됨). 이미 JSON 있으면 묻고, 동의 시 재실행.
# JSON 경로 (lerobot 기본):
#   ~/.cache/huggingface/lerobot/calibration/robots/openarm_follower/$CALIBRATION_ID.json
stage_calibrate_follower() {
  log "[calibrate] lerobot openarm_follower 양팔 캘리브레이션"
  if ! command -v lerobot-calibrate &>/dev/null; then
    log "  ✗ lerobot-calibrate 명령 없음 — 현재 env 에 lerobot 미설치" >&2
    log "    같은 env (pdg) 에 lerobot 설치 후 재실행." >&2
    return 1
  fi
  check_can_interfaces

  local cal_dir="$HOME/.cache/huggingface/lerobot/calibration/robots/openarm_follower"
  local cal_file="$cal_dir/$CALIBRATION_ID.json"
  local do_run=1
  if [[ -f "$cal_file" ]]; then
    log "  ✓ 기존 JSON 존재: $cal_file"
    local answer
    read -rp "  다시 캘리브레이션 하시겠습니까? [y/N]: " answer >&2
    case "$answer" in
      y|Y|yes|YES) do_run=1 ;;
      *)           log "  → 기존 JSON 그대로 사용"; return 0 ;;
    esac
  fi

  if [[ "$do_run" -eq 1 ]]; then
    log "  [1/2] 오른팔 ($RIGHT_CAN)"
    lerobot-calibrate \
      --robot.type=openarm_follower \
      --robot.port="$RIGHT_CAN" \
      --robot.side=right \
      --robot.id="$CALIBRATION_ID" \
      || { log "  ✗ 오른팔 캘리브레이션 실패" >&2; return 1; }

    log "  [2/2] 왼팔 ($LEFT_CAN)"
    lerobot-calibrate \
      --robot.type=openarm_follower \
      --robot.port="$LEFT_CAN" \
      --robot.side=left \
      --robot.id="$CALIBRATION_ID" \
      || { log "  ✗ 왼팔 캘리브레이션 실패" >&2; return 1; }

    log "  ✓ 양팔 캘리브레이션 완료"
  fi
}

# --- 0. CAN-FD 인터페이스 설정 (1회/부팅) -------------------------------
# lerobot-setup-can --mode=setup : CAN-FD bitrate 등을 잡음 (sudo 필요할 수 있음).
# 부팅 후 한 번만 실행. 모터 점검 / bringup 은 인터페이스가 이미 UP 인 상태 가정.
stage_can_setup_only() {
  log "[인터페이스 설정] CAN-FD setup"
  if ! command -v lerobot-setup-can &>/dev/null; then
    log "  ✗ lerobot-setup-can 명령 없음 — 같은 env (pdg) 에 lerobot 설치 필요" >&2
    return 1
  fi
  local IFACES="$RIGHT_CAN,$LEFT_CAN"
  lerobot-setup-can --mode=setup --interfaces="$IFACES" \
    || { log "  ✗ CAN-FD setup 실패" >&2; return 1; }
  log "  ✓ 인터페이스 설정 완료 ($IFACES)"
}

# --- 1. 통신 & 모터 점검 (lerobot-setup-can --mode=test) ---------------
# 사전조건: 0 번 (인터페이스 설정) 으로 CAN 이 UP. UP 여부 ip link 로 확인하고
# lerobot-setup-can --mode=test 로 양팔 모터 ping.
stage_can_motor_test() {
  log "[통신 & 모터 점검] 모터 ping test"

  log "  [1/2] CAN 인터페이스 UP 여부 확인"
  local CAN_LINES
  CAN_LINES=$(ip link show 2>/dev/null | grep -E 'can[0-9]' || true)
  if [[ -z "$CAN_LINES" ]]; then
    log "  ✗ can* 인터페이스 없음 — 0번 (인터페이스 설정) 먼저 실행" >&2
    return 1
  fi
  echo "$CAN_LINES" | sed 's/^/    /'
  for IF in "$RIGHT_CAN" "$LEFT_CAN"; do
    if ! ip link show "$IF" &>/dev/null; then
      log "  ✗ $IF 없음 — 0번 (인터페이스 설정) 먼저 실행" >&2
      return 1
    fi
  done

  if ! command -v lerobot-setup-can &>/dev/null; then
    log "  ✗ lerobot-setup-can 명령 없음" >&2
    return 1
  fi

  log "  [2/2] 모터 ping test (lerobot-setup-can --mode=test)"
  local IFACES="$RIGHT_CAN,$LEFT_CAN"
  lerobot-setup-can --mode=test --interfaces="$IFACES" \
    || { log "  ✗ 모터 test 실패 — 전원·결선·ID 확인" >&2; return 1; }

  log "✓ 모터 점검 통과"
}

# --- bringup tmux 띄움 (mock 또는 real) ---------------------------------
stage_bringup() {
  local HARDWARE_TYPE="$1"  # mock | real

  if tmux has-session -t "$SESSION" 2>/dev/null; then
    # 기존 세션의 hardware_type 을 첫 윈도우 명령에서 추출해 mode mismatch 검사.
    local CUR_HW
    CUR_HW=$(tmux list-windows -t "$SESSION" -F '#{window_name} #{pane_current_command}' 2>/dev/null | true)
    local CUR_CMD
    CUR_CMD=$(tmux display-message -t "$SESSION:bringup" -p '#{pane_start_command}' 2>/dev/null || true)
    # pane_start_command 에서 hardware_type=... 추출
    local CUR_MODE=""
    if [[ "$CUR_CMD" == *"hardware_type=real"* ]]; then
      CUR_MODE="real"
    elif [[ "$CUR_CMD" == *"hardware_type=mock"* ]]; then
      CUR_MODE="mock"
    fi
    if [[ -n "$CUR_MODE" && "$CUR_MODE" != "$HARDWARE_TYPE" ]]; then
      log "✗ 기존 세션 '$SESSION' 이 hardware_type=$CUR_MODE 로 떠 있음 (요청: $HARDWARE_TYPE)" >&2
      log "  먼저 'scripts/device-eduping.sh down' 으로 종료한 뒤 재시도." >&2
      exit 1
    fi
    log "세션 '$SESSION' 이미 떠있음 (hardware_type=${CUR_MODE:-unknown}) — attach"
    exec tmux attach -t "$SESSION"
  fi
  require_env

  # eduarm 의 wrapper launch — upstream openarm.bimanual 을 IncludeLaunchDescription 으로
  # 그대로 부르되 RViz 만 TimerAction 으로 죽임 (robot-web 의 three.js 가 시각화 담당).
  BRINGUP_CMD="bash -lc 'source $ROS_SETUP && source $WS_SETUP && \
    ros2 launch eduarm follower_bimanual.launch.py \
      arm_type:=$ARM_TYPE hardware_type:=$HARDWARE_TYPE \
      right_can_interface:=$RIGHT_CAN left_can_interface:=$LEFT_CAN'"

  tmux new-session -d -s "$SESSION" -x 200 -y 50 -n bringup -c "$WS_DIR" "$BRINGUP_CMD"
  tmux set-option -t "$SESSION" -g remain-on-exit on
  tmux set-option -t "$SESSION" -g mouse on
  tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
  tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
  tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
  tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

  # 카메라 상시 세트 (단일 opener + bridge + 무궁화 perception) — 팔과 독립된 별도 윈도.
  # CAN/모터 실패와 무관하게 카메라/perception 이 뜬다. perception 의 YOLO 는 idle 이며
  # robot-web 무궁화 진입 시에만 추론.
  #
  # control 서버 host 선택 (2-머신: eduping → 의사 머신). CONTROL_URL 이 명시돼 있으면
  # 그대로 존중(back-compat), 아니면 CONTROL/2번째 인자/메뉴로 host 를 골라 ws/http/server_host
  # 셋을 한 host 로 구성. d435 uploader(:8000) + depth streamer(:8100) 둘 다 그 host 로.
  local d435_server_host_arg=""
  if [[ -z "${CONTROL_URL:-}" ]]; then
    local ctrl_host
    local ctrl_sel="${CONTROL_ARG:-${CONTROL:-}}"
    if [[ -n "$ctrl_sel" ]]; then
      ctrl_host="$(_runlib::resolve_control_token "$ctrl_sel" "$REPO_ROOT/shared/machine_ips.json")" \
        || { log "✗ control 서버 '$ctrl_sel' 해석 실패 — 중단" >&2; exit 1; }
    elif [[ -t 0 ]]; then
      ctrl_host="$(_runlib::choose_control_host "Control 서버 (eduping d435 uploader :8000 / depth :8100)" "$REPO_ROOT/shared/machine_ips.json")"
    else
      ctrl_host="localhost"
    fi
    CONTROL_URL="ws://$ctrl_host:8000"
    RECOGNIZE_BASE_URL="${RECOGNIZE_BASE_URL:-http://$ctrl_host:8000}"
    d435_server_host_arg=" server_host:=$ctrl_host"
    log "control 서버 host=$ctrl_host → control_url=$CONTROL_URL"
  fi
  # ros2 launch 는 빈 'device_token:=' 를 거부 — 토큰 있을 때만 인자 추가 (없으면 launch 기본값 "").
  local d435_token_arg=""
  [[ -n "${DEVICE_TOKEN:-}" ]] && d435_token_arg=" device_token:=$DEVICE_TOKEN"
  D435_CMD="bash -lc 'source $ROS_SETUP && source $WS_SETUP && \
    ros2 launch eduarm eduping_d435_base.launch.py \
      control_url:=${CONTROL_URL:-ws://localhost:8000} \
      recognize_base_url:=${RECOGNIZE_BASE_URL:-http://localhost:8000}$d435_server_host_arg$d435_token_arg'"
  tmux new-window -t "$SESSION" -n d435 -c "$WS_DIR" "$D435_CMD"

  # 청진기 압전(FSR) 브리지 — Arduino(udev 심볼릭 /dev/eduping_stetho) → /eduping/stethoscope/fsr_raw.
  # eduping 노트북에 물린 하드웨어라 카메라처럼 device 세트에 같이 둔다. 팔/카메라와
  # 독립된 별도 윈도 — 노드가 serial 실패 시 2s 재시도라 Arduino 미연결이어도 안 닫힘.
  # 포트는 99-eduping-stethoscope.rules 의 고정 심볼릭(/dev/eduping_stetho) — /dev/ttyACM* 가
  # 바뀌어도 항상 같은 보드. 다른 포트면 STETHO_PORT=/dev/ttyACM0 식으로 override.
  # 하드웨어 없이 doctor UI 검증: STETHO_FAKE=1 → 합성 sine 값 publish.
  local stetho_fake="false"
  case "${STETHO_FAKE:-}" in 1|true|yes|on) stetho_fake="true" ;; esac
  local stetho_port="${STETHO_PORT:-/dev/eduping_stetho}"
  # FSR 도 카메라처럼 control 서버로 WS push (위에서 고른 host). ROS DDS cross-machine 회피.
  STETHO_CMD="bash -lc 'source $ROS_SETUP && source $WS_SETUP && \
    ros2 launch eduping_stethoscope stethoscope.launch.py fake:=$stetho_fake serial_port:=$stetho_port \
      control_url:=${CONTROL_URL:-ws://localhost:8000}'"
  tmux new-window -t "$SESSION" -n stetho -c "$WS_DIR" "$STETHO_CMD"

  # Doctor telehealth — 양방향 teleop WS 브리지 + leader_passthrough (고정주기 + One Euro + 속도캡).
  #   [teleop] teleop_ws_robot_node: control 서버 WS ↔ 로컬. leader 수신 → /eduping/leader/joint_states,
  #            실물 /joint_states → 서버 (doctor three.js 가 실제 자세로 움직이게).
  #   [pass]   leader_passthrough_node: leader → One Euro 필터(떨림 제거) + 속도 캡 → JTC.
  #            start_active:=true — 게이트는 control-service teleop relay 가 담당 (telehealth 정지 시
  #            leader 프레임 forward 안 됨).
  TELEOP_WS_CMD="bash -lc 'source $ROS_SETUP && source $WS_SETUP && \
    ros2 run eduarm teleop_ws_robot_node --ros-args \
      -p control_url:=${CONTROL_URL:-ws://localhost:8000}'"
  tmux new-window -t "$SESSION" -n teleop -c "$WS_DIR" "$TELEOP_WS_CMD"

  # ── teleop 튜닝 (아래 값만 바꿔 device-eduping.sh 재기동) ──────────────────
  # 단순 직결 passthrough — leader 를 받는 즉시 JTC publish, 부드러움은 보간창으로.
  PASS_INTERP_S=0.12     # JTC 보간창(s). ↑ 더 부드럽지만 지연↑ (떨림 시 0.15~0.25 로)
  PASS_MAX_VEL=1.0       # per-joint 최대 각속도(rad/s) — 안전 캡
  PASSTHROUGH_CMD="bash -lc 'source $ROS_SETUP && source $WS_SETUP && \
    ros2 run eduarm leader_passthrough_node --ros-args -p start_active:=true \
      -p interp_s:=$PASS_INTERP_S -p max_joint_vel:=$PASS_MAX_VEL'"
  tmux new-window -t "$SESSION" -n pass -c "$WS_DIR" "$PASSTHROUGH_CMD"

  log "세션 '$SESSION' 시작 — [bringup] arm_type=$ARM_TYPE hardware_type=$HARDWARE_TYPE right=$RIGHT_CAN left=$LEFT_CAN  + [d435] 카메라 상시 세트  + [stetho] 청진기 FSR (fake=$stetho_fake)  + [teleop] WS 브리지  + [pass] leader_passthrough"
  log "/joint_states 토픽이 살아나면 sim twin / Control Server 가 구독 가능. d435 윈도엔 카메라/bridge/perception, stetho 윈도엔 /eduping/stethoscope/fsr_raw."
  log "telehealth: doctor UI '시작' → leader → [teleop]수신 → [pass]단순 JTC(속도캡) → 실물 follower. 실물 자세는 [teleop]→서버→doctor three.js 로 반영."
  exec tmux attach -t "$SESSION"
}

# --- 인터랙티브 메뉴 -----------------------------------------------------
prompt_menu() {
  cat >&2 <<EOF
=== eduping-device 메뉴 ===
  0) 인터페이스 설정      (lerobot-setup-can --mode=setup, 부팅 후 1회)
  1) 통신 & 모터 점검     (lerobot-setup-can --mode=test, 양팔 ping)
  2) calibrate           (lerobot openarm_follower 양팔 캘리브레이션)
  3) real bringup        (모터 점검 → 실물 hardware_type=real)
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
  0|setup|interface)
    stage_can_setup_only
    ;;
  1|check|test|comm)
    stage_can_motor_test
    ;;
  2|c|cal|calibrate)
    stage_calibrate_follower
    ;;
  3|real|up)
    stage_bringup "real"
    ;;
  d|down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      # graceful: ros2 launch 가 노드(특히 realsense2_camera — D435 점유)를 정리하도록 각
      # 윈도에 SIGINT(Ctrl-C) 먼저. abrupt kill-session(SIGHUP)만 하면 launch 자식 노드가
      # orphan 으로 남아 D435 'device busy' 를 유발한다.
      for w in $(tmux list-windows -t "$SESSION" -F '#{window_index}' 2>/dev/null); do
        tmux send-keys -t "$SESSION:$w" C-c 2>/dev/null || true
      done
      sleep 3
      tmux kill-session -t "$SESSION" 2>/dev/null || true
      log "세션 '$SESSION' 종료 (graceful — SIGINT 후 정리)"
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
    echo "usage: $0 [0|1|2|3|setup|check|calibrate|real|down|status]" >&2
    exit 2
    ;;
esac
