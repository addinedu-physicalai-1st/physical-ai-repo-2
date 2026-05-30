#!/usr/bin/env bash
# Doctor teleop bringup — **의사 컴 (doctor machine).**
#
# 배포 구성 (2-머신):
#   - 이 머신 = 의사 + 리드디바이스. run_server.sh (control :8000) + 이 스크립트.
#   - eduping(로봇) 머신 = follower(OpenArm CAN) + D435 + 청진기 → device-eduping.sh.
#     follower 제어/상태는 control 서버(:8000) WS 경유 (ROS 도메인 공유 아님).
#
# 그래서 이 머신엔 실물 follower 가 없다 — doctor_teleop 을 **mock follower** 로 띄워
# doctor UI 시각화만 담당하고, 실물 팔은 eduping 머신이 control 서버 통해 받는다.
#   기본: USE_FAKE_HARDWARE=true (mock). 드물게 follower 가 이 머신에 물려 있으면
#         USE_FAKE_HARDWARE=false scripts/device-doctor.sh start 로 override.
#
# 실물 mini leader (Feetech 양팔 USB) 도 같이 기동 — 별도 'leader' 윈도에서
# feetech_leader_node 가 /eduping/leader/joint_states 를 publish 하고, 'ros' 윈도의
# leader_passthrough 가 그걸 구독해 (mock) follower → doctor UI 로 흘린다. 한 명령으로.
#
# ⚠ 사전 준비:
#   - **leader: feetech-servo-sdk 가 깔린 conda env 활성** 후 실행. 이 스크립트는
#     conda activate 를 하지 않고 호출 셸 env 를 그대로 상속한다 (예: conda activate pdg).
#     leader 윈도만 그 env 가 필요 — 나머지 노드는 system python (고정 shebang) 사용.
#   - leader USB 포트 (기본 udev 심볼릭): /dev/op_mini_right, /dev/op_mini_left
#       symlink 없으면 PORT_RIGHT=/dev/ttyACM0 PORT_LEFT=/dev/ttyACM1 prefix 로 지정.
#   - (USE_FAKE_HARDWARE=false override 시에만) PEAK CAN can0/can1 UP + 16모터 preflight.
#
# 다른 런처:
#   - run_server.sh             → control-service :8000 (eduping 머신이 LAN IP:8000 로 접속)
#   - ui-portal.sh              → portal-web :5174 (doctor UI)
#   - device-eduping.sh         → eduping 머신: follower + D435 + 청진기
#   - device-eduping-leader.sh  → leader 만 단독 기동/점검/calibration (이 스크립트와 토픽 공유)
#
# 사용:
#   device-doctor.sh start
#   device-doctor.sh start --rviz
#   device-doctor.sh stop
#   device-doctor.sh status
#   device-doctor.sh attach

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.run/doctor"
TMUX_SESSION="doctor"
mkdir -p "$PID_DIR"

# bash 내부 ros launch 명령 — RViz 는 doctor_rviz.launch.py 로 분리.
# RMW 는 호출 셸의 환경변수를 그대로 상속 (시스템 default = Fast DDS).
# 빌드는 루트에서 `colcon build` → 모든 패키지가 $ROOT/install/ 에 모임.
build_ros_cmd() {
  # 카메라 mount 보정 — 환경변수 또는 기본값. 위로 10° 들렸으면 -0.1745.
  local pitch="${CAM_PITCH:--0.1745}"
  local yaw="${CAM_YAW:-0.0}"
  local roll="${CAM_ROLL:-0.0}"
  # 기본 mock_components (sim) — 이 머신엔 실물 follower 없음. doctor_teleop.launch.py 가
  # USE_FAKE_HARDWARE 읽음. follower 가 이 머신에 물린 경우만 false override.
  local fake_hw="${USE_FAKE_HARDWARE:-true}"
  echo "export USE_FAKE_HARDWARE=$fake_hw && \
        source $ROOT/install/setup.bash && \
        exec ros2 launch eduarm doctor_teleop.launch.py rviz:=false \
            cam_pitch:=$pitch cam_yaw:=$yaw cam_roll:=$roll"
}
build_rviz_cmd() {
  echo "source $ROOT/install/setup.bash && \
        exec ros2 launch eduarm doctor_rviz.launch.py"
}
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
# leader 윈도가 import 에러로 즉사하기 전에 미리 경고 — 나머지 노드는 그대로 기동.
preflight_leader_env() {
  if ! python -c "import scservo_sdk" >/dev/null 2>&1; then
    echo "[leader] ⚠ 현재 python 에 scservo_sdk(feetech-servo-sdk) 없음 — leader 윈도가 import 에러로 종료됩니다." >&2
    echo "[leader]   feetech-servo-sdk 설치된 env 활성화 후 재실행하세요 (예: conda activate pdg)." >&2
    echo "[leader]   나머지 ROS 노드는 정상 기동됩니다." >&2
  fi
}

start_bg() {
  local rviz_flag="$1"
  local logf="$PID_DIR/ros.log"
  echo "[ros] starting → $logf"
  setsid bash -c "$(build_ros_cmd) >\"$logf\" 2>&1" &
  echo $! >"$PID_DIR/ros.pid"
  # 청진기 FSR 브리지 / follower 는 eduping 머신 (device-eduping.sh) 에서 띄움 — 여기 아님.
  # 실물 mini leader — 호출 셸의 활성 env 를 그대로 상속 (conda activate 안 함).
  preflight_leader_env
  local leaderf="$PID_DIR/leader.log"
  echo "[leader] starting → $leaderf"
  setsid bash -c "$(build_leader_cmd) >\"$leaderf\" 2>&1" &
  echo $! >"$PID_DIR/leader.pid"
  if [ "$rviz_flag" = "true" ]; then
    local rvizf="$PID_DIR/rviz.log"
    echo "[rviz] starting → $rvizf"
    setsid bash -c "$(build_rviz_cmd) >\"$rvizf\" 2>&1" &
    echo $! >"$PID_DIR/rviz.pid"
  fi
}

start_tmux() {
  local rviz_flag="$1"
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
  # ROS setup.bash 는 BASH_SOURCE 가 필요 → bash 로 명시적 실행.
  # window 'ros'    = move_group + JTC + leader_passthrough + (mock) follower.
  # window 'leader' = 실물 mini leader (feetech_leader_node). HW 가 죽어도 독립 재시작
  #                   가능하도록 별도 윈도. remain-on-exit 로 self-check 실패 로그 보존.
  # window 'rviz'   = RViz 만 (분리 — 따로 죽이거나 재시작 가능).
  # (follower 실물 / D435 / 청진기는 eduping 머신의 device-eduping.sh — 여기 아님.)
  tmux new-session -d -s "$TMUX_SESSION" -n ros bash -c "$(build_ros_cmd)"
  # 실물 mini leader — 호출 셸의 활성 env (feetech-servo-sdk) 를 그대로 상속.
  tmux new-window -t "$TMUX_SESSION" -n leader bash -c "$(build_leader_cmd)"
  tmux set-option -t "$TMUX_SESSION:leader" remain-on-exit on
  tmux select-window -t "$TMUX_SESSION:ros"
  if [ "$rviz_flag" = "true" ]; then
    tmux new-window -t "$TMUX_SESSION" -n rviz bash -c "$(build_rviz_cmd)"
  fi
  echo "$TMUX_SESSION" >"$PID_DIR/tmux.session"
  tmux attach -t "$TMUX_SESSION"
}

restart_rviz_tmux() {
  if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
    echo "[tmux] session '$TMUX_SESSION' 안 떠있음 — 'start' 먼저" >&2
    return 1
  fi
  if tmux list-windows -t "$TMUX_SESSION" -F '#W' | grep -q '^rviz$'; then
    echo "[rviz] killing existing rviz window"
    tmux kill-window -t "$TMUX_SESSION:rviz" 2>/dev/null || true
  fi
  echo "[rviz] starting rviz window"
  tmux new-window -t "$TMUX_SESSION" -n rviz bash -c "$(build_rviz_cmd)"
}

stop_all() {
  # tmux 세션 우선 정리.
  if [ -f "$PID_DIR/tmux.session" ]; then
    local sess
    sess=$(cat "$PID_DIR/tmux.session")
    if tmux has-session -t "$sess" 2>/dev/null; then
      # attached client 먼저 detach — 그래야 client 가 terminal mode (mouse tracking 등)
      # 를 정상 복구하고 종료. detach 없이 kill-session 하면 SIGHUP 으로 죽어
      # 마우스 휠 입력이 escape sequence 로 깨져 보임.
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
  # 본 스크립트가 띄울 수 있는 모든 ROS 노드를 강제 종료 — 이전 launch 에서
  # parent 가 죽었는데 child 들이 orphan 으로 살아남는 경우 대비. doctor_teleop.launch
  # 가 띄우는 노드들을 모두 명시.
  echo "[cleanup] forcing kill of any leftover ROS nodes from doctor_teleop"
  pkill -KILL -f "ros2 launch eduarm doctor_teleop" 2>/dev/null || true
  pkill -KILL -f "doctor_teleop.launch.py"          2>/dev/null || true
  # 실물 mini leader (별도 윈도/백그라운드) — python -m eduarm.feetech_leader_node.
  pkill -KILL -f "eduarm.feetech_leader_node"       2>/dev/null || true
  pkill -KILL -f "feetech_leader_node"              2>/dev/null || true
  pkill -KILL -f "ros2_control_node"                 2>/dev/null || true
  pkill -KILL -f "lib/moveit_ros_move_group/move_group" 2>/dev/null || true
  pkill -KILL -f "lib/moveit_servo/servo_node"       2>/dev/null || true
  pkill -KILL -f "robot_state_publisher"             2>/dev/null || true
  pkill -KILL -f "eduarm/lib/eduarm/joint_state_relay"   2>/dev/null || true
  pkill -KILL -f "eduarm/lib/eduarm/home_pose_setter"    2>/dev/null || true
  pkill -KILL -f "eduarm/lib/eduarm/leader_passthrough"  2>/dev/null || true
  pkill -KILL -f "rviz2"                             2>/dev/null || true
  sleep 1
}

cmd="${1:-start}"
shift || true
rviz_arg="false"           # 기본 RViz OFF — doctor UI 가 메인 뷰. 필요 시 --rviz.
use_tmux=1                 # 기본 tmux 모드.
for arg in "$@"; do
  case "$arg" in
    --rviz)    rviz_arg="true" ;;
    --no-rviz) rviz_arg="false" ;;  # 명시적 OFF (기본과 동일, 호환성).
    --bg)      use_tmux=0 ;;
    --tmux)    use_tmux=1 ;;        # 명시적 ON (기본과 동일).
    *) echo "unknown flag: $arg"; exit 1 ;;
  esac
done

case "$cmd" in
  start)
    if [ "$use_tmux" -eq 1 ]; then
      start_tmux "$rviz_arg"
      echo
      echo "Attach:          tmux attach -t $TMUX_SESSION   (또는 $0 attach)"
      echo "Detach (안에서): Ctrl+B 다음 D"
    else
      start_bg "$rviz_arg"
      echo
      echo "ROS launch 로그: $PID_DIR/ros.log   (실시간: tail -f $PID_DIR/ros.log)"
    fi
    if [ "$rviz_arg" = "true" ]; then
      echo "RViz:            창이 자동으로 뜸 (X11)"
    fi
    echo "Follower:        ${USE_FAKE_HARDWARE:-true} (mock) — 실물 follower 는 eduping 머신"
    echo "Leader:          'leader' 윈도에서 feetech_leader_node publish (Ctrl+B 1 로 이동)"
    echo "                 motor self-check 실패 시 그 윈도만 종료 — Ctrl+B 1 로 로그 확인 후 재시작"
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
  rviz)
    # RViz 만 (재)시작 — ROS 는 그대로 두고 RViz 만 죽었거나 닫혔을 때.
    restart_rviz_tmux
    ;;
  *)
    echo "usage: $0 start [--rviz] [--no-rviz] [--bg] | stop | attach | status | rviz"
    exit 1
    ;;
esac
