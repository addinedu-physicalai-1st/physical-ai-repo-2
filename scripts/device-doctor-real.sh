#!/usr/bin/env bash
# Doctor teleop ROS launch — **실물 OpenArm CAN HW 모드.**
#
# 시뮬 (mock_components) 로 테스트할 땐 → device-doctor-sim.sh
#
# ⚠ 사전 준비:
#   - PEAK CAN 드라이버 + can0 (오른팔) / can1 (왼팔) interface UP
#       sudo ip link set can0 up type can bitrate 1000000
#       sudo ip link set can1 up type can bitrate 1000000
#   - 양팔 16 모터 preflight (선택, 안전성 ↑):
#       openarm-can-motor-check 또는 scripts/device-eduping.sh 2
#   - 양팔이 안전 자세 (사람 없는 공간) 에서 시작 — home_pose_setter 가 skip 되므로
#     현재 자세 그대로 leader 따라감.
#
# 다른 런처:
#   - run_server.sh             → control-service :8000
#   - ui-portal.sh              → portal-web :5174
#   - device-doctor-sim.sh      → 시뮬 모드 (mock_components)
#   - device-eduping-leader.sh  → 실물 mini leader (Feetech, USB)
#
# 사용:
#   device-doctor-real.sh start
#   device-doctor-real.sh start --rviz
#   device-doctor-real.sh stop
#   device-doctor-real.sh status
#   device-doctor-real.sh attach

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.run/doctor_real"
TMUX_SESSION="doctor_real"
mkdir -p "$PID_DIR"

# bash 내부 ros launch 명령 — RViz 는 doctor_rviz.launch.py 로 분리.
# RMW 는 호출 셸의 환경변수를 그대로 상속 (시스템 default = Fast DDS).
# 빌드는 루트에서 `colcon build` → 모든 패키지가 $ROOT/install/ 에 모임.
build_ros_cmd() {
  # 카메라 mount 보정 — 환경변수 또는 기본값. 위로 10° 들렸으면 -0.1745.
  local pitch="${CAM_PITCH:--0.1745}"
  local yaw="${CAM_YAW:-0.0}"
  local roll="${CAM_ROLL:-0.0}"
  # 실물 OpenArm CAN HW. doctor_teleop.launch.py 가 USE_FAKE_HARDWARE 읽음.
  echo "export USE_FAKE_HARDWARE=false && \
        source $ROOT/install/setup.bash && \
        exec ros2 launch eduarm doctor_teleop.launch.py rviz:=false \
            cam_pitch:=$pitch cam_yaw:=$yaw cam_roll:=$roll"
}
build_rviz_cmd() {
  echo "source $ROOT/install/setup.bash && \
        exec ros2 launch eduarm doctor_rviz.launch.py"
}

start_bg() {
  local rviz_flag="$1"
  local logf="$PID_DIR/ros.log"
  echo "[ros] starting → $logf"
  setsid bash -c "$(build_ros_cmd) >\"$logf\" 2>&1" &
  echo $! >"$PID_DIR/ros.pid"
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
  # ROS setup.bash 는 BASH_SOURCE 가 필요 → bash 로 명시적 실행.
  # window 'ros' = move_group + D435 + JTC + leader_passthrough.
  # window 'rviz' = RViz 만 (분리 — 따로 죽이거나 재시작 가능).
  tmux new-session -d -s "$TMUX_SESSION" -n ros bash -c "$(build_ros_cmd)"
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
  pkill -KILL -f "ros2_control_node"                 2>/dev/null || true
  pkill -KILL -f "lib/moveit_ros_move_group/move_group" 2>/dev/null || true
  pkill -KILL -f "lib/moveit_servo/servo_node"       2>/dev/null || true
  pkill -KILL -f "robot_state_publisher"             2>/dev/null || true
  pkill -KILL -f "eduarm/lib/eduarm/joint_state_relay"   2>/dev/null || true
  pkill -KILL -f "eduarm/lib/eduarm/home_pose_setter"    2>/dev/null || true
  pkill -KILL -f "eduarm/lib/eduarm/leader_passthrough"  2>/dev/null || true
  pkill -KILL -f "eduarm/lib/eduarm/d435_rgb_uploader"   2>/dev/null || true
  pkill -KILL -f "eduarm/lib/eduarm/d435_pointcloud_uploader" 2>/dev/null || true
  # realsense2_camera_node — 카메라 device 점유 풀어줘야 다음 launch 가 성공.
  pkill -KILL -f "realsense2_camera/realsense2_camera_node" 2>/dev/null || true
  pkill -KILL -f "octomap_server/octomap_server_node"    2>/dev/null || true
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
    echo "usage: $0 start [--no-rviz] [--bg] | stop | attach | status | rviz"
    exit 1
    ;;
esac
