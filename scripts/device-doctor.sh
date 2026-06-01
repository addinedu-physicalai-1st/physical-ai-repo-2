#!/usr/bin/env bash
# Doctor leader bringup — **의사 컴 (doctor machine).**
#
# 배포 구성 (2-머신, ROS 도메인 분리 a-2):
#   - 이 머신 = 의사 + 리드디바이스 (ROS_DOMAIN_ID 예: 205).
#       run_server.sh (control :8000) + 이 스크립트 (feetech leader + WS uploader).
#   - eduping(로봇) 머신 (예: 202) = follower(OpenArm CAN) + D435 + 청진기 + teleop_ws_robot
#       + leader_passthrough → device-eduping.sh.
#
# 이 스크립트는 **leader 만** 담당한다 (mock follower / move_group / RViz 안 띄움):
#   window 'leader' = feetech_leader_node → /eduping/leader/joint_states (이 머신 로컬, 205).
#   window 'lup'    = leader_ws_uploader_node → control-service WS (/ws/eduping/teleop?role=leader_src).
#
# 도메인이 분리돼 있어 leader 토픽은 DDS 로 woobuntu 에 안 감 — control 서버(:8000) WS
# relay 가 woobuntu(teleop_ws_robot)로 forward 한다. follower 실물 구동·doctor 3D 피드백은
# 전부 WS 경유. (실물 follower / leader_passthrough / D435 / 청진기는 eduping 머신.)
#
# ⚠ 사전 준비:
#   - **conda env (feetech-servo-sdk 보유, 예: pdg) 활성 후 실행.** 이 스크립트는 conda
#     activate 를 하지 않고 호출 셸 env 를 그대로 상속한다. 'leader' 윈도만 그 env 가
#     필요 — 'lup' 은 system python (ros2 run 고정 shebang) + websockets 사용.
#   - leader USB 포트 (기본 udev 심볼릭): /dev/op_mini_right, /dev/op_mini_left
#       symlink 없으면 PORT_RIGHT=/dev/ttyACM0 PORT_LEFT=/dev/ttyACM1 prefix 로 지정.
#   - eduarm 재빌드 필요 (leader_ws_uploader_node entry point):
#       colcon build --symlink-install --packages-select eduarm
#
# 다른 런처:
#   - run_server.sh             → control-service :8000 (relay 허브)
#   - ui-portal.sh              → portal-web :5174 (doctor UI)
#   - device-eduping.sh         → eduping 머신: follower + teleop_ws_robot + leader_passthrough + D435 + 청진기
#   - device-eduping-leader.sh  → leader 만 단독 기동/점검/calibration (이 스크립트와 토픽 공유)
#
# 사용:
#   device-doctor.sh start
#   device-doctor.sh stop
#   device-doctor.sh status
#   device-doctor.sh attach

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.run/doctor"
TMUX_SESSION="doctor"
mkdir -p "$PID_DIR"

build_leader_cmd() {
  # 실물 mini leader (Feetech 양팔 USB) → /eduping/leader/joint_states publisher.
  # device-eduping-leader.sh 의 bringup 과 동일한 노드/파라미터 — env 변수명도 공유.
  # ⚠ conda activate 안 함: 호출 셸의 활성 env (feetech-servo-sdk 보유) 를 그대로 상속.
  #   install/setup.bash 만 source (ROS underlay 체이닝). `python` = 현재 활성 env python.
  local port_right="${PORT_RIGHT:-/dev/op_mini_right}"
  local port_left="${PORT_LEFT:-/dev/op_mini_left}"
  local baud="${BAUDRATE:-1000000}"
  local rate="${RATE_HZ:-50.0}"
  local cal="${CALIBRATION_PATH:-$HOME/.cache/huggingface/lerobot/calibration/teleoperators/openarm_mini/my_mini_leader_arm.json}"
  echo "source $ROOT/install/setup.bash && \
        exec python -m eduarm.feetech_leader_node --ros-args \
            -p port_right:=$port_right \
            -p port_left:=$port_left \
            -p baudrate:=$baud \
            -p rate_hz:=$rate \
            -p calibration_path:=$cal"
}
build_leader_uploader_cmd() {
  # leader /eduping/leader/joint_states → control-service WS (role=leader_src).
  # 도메인 분리 (a-2): leader 가 ROS DDS 로 woobuntu 에 못 감 → WS 우회. control-service 가
  # 이 머신에 같이 떠 있으므로 localhost. relay 가 active 일 때 woobuntu 로 forward.
  # ros2 run = install shebang (system python3) — websockets 는 system python 에 필요.
  local url="${CONTROL_URL:-ws://localhost:8000}"
  echo "source $ROOT/install/setup.bash && \
        exec ros2 run eduarm leader_ws_uploader_node --ros-args \
            -p control_url:=$url"
}
# leader 윈도가 import 에러로 즉사하기 전에 미리 경고 — uploader 는 그대로 기동.
preflight_leader_env() {
  if ! python -c "import scservo_sdk" >/dev/null 2>&1; then
    echo "[leader] ⚠ 현재 python 에 scservo_sdk(feetech-servo-sdk) 없음 — leader 윈도가 import 에러로 종료됩니다." >&2
    echo "[leader]   feetech-servo-sdk 설치된 env 활성화 후 재실행하세요 (예: conda activate pdg)." >&2
    echo "[leader]   uploader(lup) 는 정상 기동됩니다." >&2
  fi
}

start_bg() {
  preflight_leader_env
  local leaderf="$PID_DIR/leader.log"
  echo "[leader] starting → $leaderf"
  setsid bash -c "$(build_leader_cmd) >\"$leaderf\" 2>&1" &
  echo $! >"$PID_DIR/leader.pid"
  # leader → control-service WS uploader (telehealth cross-machine forward).
  local lupf="$PID_DIR/leader_uploader.log"
  echo "[lup] starting → $lupf"
  setsid bash -c "$(build_leader_uploader_cmd) >\"$lupf\" 2>&1" &
  echo $! >"$PID_DIR/leader_uploader.pid"
}

start_tmux() {
  if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux not installed — apt install tmux" >&2
    exit 1
  fi
  if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    echo "[tmux] session '$TMUX_SESSION' already running — attach 또는 stop 먼저"
    return 1
  fi
  echo "[tmux] starting session '$TMUX_SESSION' (자동 attach — Ctrl+B D 로 detach)"
  preflight_leader_env
  # window 'leader' = 실물 mini leader (feetech_leader_node). 호출 셸의 활성 env 상속.
  #                   HW self-check 실패 시 그 윈도만 죽음 — remain-on-exit 로 로그 보존.
  # window 'lup'    = leader_ws_uploader_node → control-service WS.
  tmux new-session -d -s "$TMUX_SESSION" -n leader bash -c "$(build_leader_cmd)"
  tmux set-option -t "$TMUX_SESSION:leader" remain-on-exit on
  tmux new-window -t "$TMUX_SESSION" -n lup bash -c "$(build_leader_uploader_cmd)"
  tmux set-option -t "$TMUX_SESSION:lup" remain-on-exit on
  tmux select-window -t "$TMUX_SESSION:leader"
  echo "$TMUX_SESSION" >"$PID_DIR/tmux.session"
  tmux attach -t "$TMUX_SESSION"
}

stop_all() {
  # tmux 세션 우선 정리.
  if [ -f "$PID_DIR/tmux.session" ]; then
    local sess
    sess=$(cat "$PID_DIR/tmux.session")
    if tmux has-session -t "$sess" 2>/dev/null; then
      # attached client 먼저 detach — 그래야 client 가 terminal mode (mouse tracking 등)
      # 를 정상 복구하고 종료.
      tmux detach-client -s "$sess" -a 2>/dev/null || true
      sleep 0.1
      echo "killing tmux session $sess"
      tmux kill-session -t "$sess" || true
    fi
    rm -f "$PID_DIR/tmux.session"
  fi
  # 백그라운드 PID 정리.
  for pidf in "$PID_DIR"/*.pid; do
    [ -f "$pidf" ] || continue
    local pid; pid=$(cat "$pidf")
    if kill -0 "$pid" 2>/dev/null; then
      echo "killing $(basename "$pidf" .pid) pgroup -$pid"
      kill -TERM -"$pid" 2>/dev/null || true
      sleep 1
      kill -KILL -"$pid" 2>/dev/null || true
    fi
    rm -f "$pidf"
  done
  # orphan 노드 강제 종료 (이 스크립트가 띄우는 것만).
  echo "[cleanup] forcing kill of leftover leader / uploader nodes"
  pkill -KILL -f "eduarm.feetech_leader_node"       2>/dev/null || true
  pkill -KILL -f "feetech_leader_node"              2>/dev/null || true
  pkill -KILL -f "leader_ws_uploader_node"          2>/dev/null || true
  sleep 1
}

cmd="${1:-start}"
shift || true
use_tmux=1                 # 기본 tmux 모드.
for arg in "$@"; do
  case "$arg" in
    --bg)   use_tmux=0 ;;
    --tmux) use_tmux=1 ;;        # 명시적 ON (기본과 동일).
    *) echo "unknown flag: $arg"; exit 1 ;;
  esac
done

case "$cmd" in
  start)
    if [ "$use_tmux" -eq 1 ]; then
      start_tmux
      echo
      echo "Attach:          tmux attach -t $TMUX_SESSION   (또는 $0 attach)"
      echo "Detach (안에서): Ctrl+B 다음 D"
    else
      start_bg
      echo
      echo "leader 로그: $PID_DIR/leader.log   uploader 로그: $PID_DIR/leader_uploader.log"
    fi
    echo "Leader:          'leader' 윈도 feetech_leader_node → /eduping/leader/joint_states"
    echo "                 motor self-check 실패 시 그 윈도만 종료 — Ctrl+B 0 으로 로그 확인 후 재시작"
    echo "Uploader:        'lup' 윈도 leader_ws_uploader_node → control :8000 WS relay"
    echo "Web UI:          http://localhost:5174/doctor/teleop?eduping_id=ed-01"
    echo "                 (run_server.sh + ui-portal.sh 가 떠 있어야 함)"
    echo "Stop:            $0 stop"
    ;;
  stop)
    stop_all
    ;;
  attach)
    if [ -f "$PID_DIR/tmux.session" ]; then
      exec tmux attach -t "$(cat "$PID_DIR/tmux.session")"
    else
      echo "no tmux session active — 'start --tmux' 로 시작했어야 함" >&2
      exit 1
    fi
    ;;
  status)
    if [ -f "$PID_DIR/tmux.session" ]; then
      local_sess=$(cat "$PID_DIR/tmux.session")
      if tmux has-session -t "$local_sess" 2>/dev/null; then
        echo "[tmux] session=$local_sess (active)"
      else
        echo "[tmux] session=$local_sess (gone, stale file)"
      fi
    fi
    for pidf in "$PID_DIR"/*.pid; do
      [ -f "$pidf" ] || continue
      local_name=$(basename "$pidf" .pid)
      local_pid=$(cat "$pidf")
      if kill -0 "$local_pid" 2>/dev/null; then
        echo "[$local_name] pid=$local_pid"
      else
        echo "[$local_name] stale pidfile"
      fi
    done
    ;;
  *)
    echo "usage: $0 start [--bg] | stop | attach | status"
    exit 1
    ;;
esac
