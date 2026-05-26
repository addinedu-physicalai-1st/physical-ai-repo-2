#!/usr/bin/env bash
# Doctor teleop ROS launch 만 띄움.
#
# 다른 런처 책임 분리:
#   - run_server.sh    → control-service :8000 / streaming :8100 / pgweb / ai-hub
#   - ui-portal.sh     → portal-web :5174
#   - doctor_sim.sh    → ROS 측 eduarm doctor_teleop launch 만 (이 파일)
#
# 사용:
#   doctor_sim.sh start             # tmux + RViz (기본, 저장된 moveit.rviz 자동 로드)
#   doctor_sim.sh start --no-rviz   # RViz 없이
#   doctor_sim.sh start --bg        # tmux 대신 백그라운드 + 로그 파일
#   doctor_sim.sh stop              # 띄운 ROS launch / tmux 모두 종료
#   doctor_sim.sh status            # PID/tmux 상태
#   doctor_sim.sh attach            # tmux 세션 attach (Ctrl+B D 로 detach)
#
# ─────────────────────────────────────────────
# 수동 검증 체크리스트 (Acceptance — 8 시나리오)
# ─────────────────────────────────────────────
# 사전: run_server.sh + ui-portal.sh 띄워둔 상태
# 1. http://localhost:5174/doctor/teleop?eduping_id=ed-01 접속 → 3D 캔버스 + 양팔 URDF
# 2. 핸들 (파랑) 드래그 → 좌팔 30Hz 추종
# 3. 핸들 (주황) 드래그 → 우팔 추종
# 4. Shift+wheel on 핸들 → gripper 폭 변화
# 5. 일반 wheel → OrbitControls zoom
# 6. D435 시야에 손바닥 → servo_status `slowed`
# 7. 손바닥 매우 가까이 → servo_status `stopped`
# 8. 의사 탭 새로고침 → WS 끊김 → 양팔 hold
# ─────────────────────────────────────────────

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_DIR="$ROOT/.run/doctor_sim"
TMUX_SESSION="doctor_sim"
mkdir -p "$PID_DIR"

# bash 내부 ros launch 명령 — RViz 는 doctor_rviz.launch.py 로 분리.
# RMW 는 호출 셸의 환경변수를 그대로 상속 (시스템 default = Fast DDS).
# 빌드는 루트에서 `colcon build` → 모든 패키지가 $ROOT/install/ 에 모임.
build_ros_cmd() {
  echo "source $ROOT/install/setup.bash && \
        exec ros2 launch eduarm doctor_teleop.launch.py rviz:=false"
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
  pkill -KILL -f "eduarm/lib/eduarm/clear_octomap_timer" 2>/dev/null || true
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
rviz_arg="true"            # 기본 RViz ON.
use_tmux=1                 # 기본 tmux 모드.
for arg in "$@"; do
  case "$arg" in
    --rviz)    rviz_arg="true" ;;   # 명시적 ON (기본과 동일, 호환성).
    --no-rviz) rviz_arg="false" ;;
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
