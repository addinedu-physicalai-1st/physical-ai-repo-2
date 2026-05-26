#!/usr/bin/env bash
# scripts/device-gogoping-sim.sh — GogoPing 가제보 시뮬레이션 launcher.
#
# 동작:
#   - tmux 세션 'gogoping-sim' 안에 window 7개 + 부가 (sim-teleport 등):
#       gazebo       : gogoping_bringup sim.launch.py
#                      (gogoping_navigation/launch_sim_with_pinky.launch.xml 을
#                       namespace=gogoping 으로 include + sim_status_publisher 노드)
#       graph-router : gogoping_navigation/graph_router.launch.xml (다익스트라 + nav2 위임)
#       modes        : gogoping_modes (FSM + BT 본체 — /gogoping/state publish,
#                      /gogoping/set_goal service. control-server 가 이 둘로 connect.)
#       sim-battery  : sim_battery_node — /gogoping/battery 1Hz publish +
#                      /gogoping/sim/set_battery_level srv 로 admin UI 슬라이더 디버그
#       sim-teleport : sim_teleport_node — gz set_pose bridge for debug 좌표 override
#       camera       : gogoping_camera camera_stream.launch.py — USB /dev/video0
#                      → UDP 9013 → streaming server (sim 환경에서도 실 USB 카메라 사용).
#                      Arduino 없으면 시리얼 에러 무시.
#       camera-pan   : gogoping_camera_pan camera_pan.launch.py — Arduino MG995 ×2
#                      pan/tilt 서보. /dev/arduino-camera 자동 udev install.
#       rviz         : rviz2 시각화
#
# 사용:
#   scripts/device-gogoping-sim.sh           # 세션 시작·attach (이미 떠있으면 attach)
#   scripts/device-gogoping-sim.sh down      # tmux 세션 + 잔여 가제보·브리지 정리
#   scripts/device-gogoping-sim.sh status    # 세션 상태
#
# 시연/디버그 환경변수 (gogoping_modes 노드에 ros-args 로 전달):
#   NO_BATTERY_SAFETY=1   BatteryLowMonitor 비활성 — 배터리 ≤20% 자동 RETURNING 차단
#   NO_ERROR_SAFETY=1     HardwareHealth / MapBoundary fault → ERROR 차단
# 예시: NO_BATTERY_SAFETY=1 NO_ERROR_SAFETY=1 scripts/device-gogoping-sim.sh
#
# 의존:
#   - tmux
#   - /opt/ros/jazzy 설치
#   - repo root 에서 colcon build 완료 (./install/setup.bash 존재)
#   - ROS_DOMAIN_ID 는 호출 셸 환경 그대로 사용 (export 안 함)
#
# 단축키 (tmux):
#   - Ctrl+B 다음 D → detach (백그라운드 유지)
set -euo pipefail

SESSION="gogoping-sim"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-up}"

ROS_SETUP="/opt/ros/jazzy/setup.zsh"
WS_SETUP="$REPO_ROOT/install/local_setup.zsh"

if ! command -v tmux &>/dev/null; then
  echo "[device-gogoping-sim] tmux 가 설치되어 있지 않습니다 (sudo apt install tmux)" >&2
  exit 1
fi

case "$ACTION" in
  up|"")
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      # remain-on-exit 때문에 ros2 launch 가 죽어도 pane 은 유지된다. 죽은 pane 에
      # 그대로 attach 하면 가제보가 안 뜨니, 세션 정리 후 아래 재기동 흐름으로.
      _dead=$(tmux list-panes -t "$SESSION:gazebo" -F '#{pane_dead}' 2>/dev/null | head -1)
      if [[ "$_dead" == "1" ]]; then
        echo "[device-gogoping-sim] 이전 세션의 pane 이 죽어있음 — 정리 후 재시작"
        tmux kill-session -t "$SESSION"
      else
        echo "[device-gogoping-sim] 세션 '$SESSION' 이미 떠있음 — attach"
        exec tmux attach -t "$SESSION"
      fi
    fi

    if [[ ! -f "$ROS_SETUP" ]]; then
      echo "[device-gogoping-sim] ROS Jazzy 가 설치되어 있지 않습니다 ($ROS_SETUP 없음)" >&2
      exit 1
    fi
    if [[ ! -f "$WS_SETUP" ]]; then
      echo "[device-gogoping-sim] workspace 가 빌드되어 있지 않습니다." >&2
      echo "[device-gogoping-sim]   cd $REPO_ROOT && colcon build --symlink-install" >&2
      exit 1
    fi

    # 같은 도메인에 두 개의 가제보가 뜨면 토픽 충돌. 외부에서 띄운 gz sim 도 차단.
    # pgrep 매칭 없을 때의 exit 1 이 pipefail+errexit 로 스크립트를 죽이지 않도록 잠시 해제.
    set +o pipefail
    _existing_gz=$(pgrep -af "gz sim" 2>/dev/null | grep -v "ruby .*gz sim" | wc -l)
    set -o pipefail
    if [[ "$_existing_gz" -gt 0 ]]; then
      echo "[device-gogoping-sim] 이미 gz sim 프로세스가 실행 중입니다 ($_existing_gz 개)." >&2
      echo "[device-gogoping-sim] scripts/device-gogoping-sim.sh down 으로 정리해 주세요." >&2
      exit 1
    fi

    SOURCE_ENV="source $ROS_SETUP && source $WS_SETUP"

    # /dev/arduino-camera (camera-pan 서보용 symlink) 없으면 udev rule 자동 install — 1회만, sudo 묻음.
    # sim 환경에서도 실 Arduino USB 연결되어 있으면 동일하게 PT 서보 동작 가능.
    # 실패해도 진행 — camera-pan window 에서 serial open 에러로 표시됨.
    if [[ ! -e /dev/arduino-camera ]]; then
      echo "[device-gogoping-sim] /dev/arduino-camera 없음 — udev rule 자동 install (sudo 묻음)"
      _arduino_dev=""
      for _d in /dev/ttyACM* /dev/ttyUSB*; do
        [[ -e "$_d" ]] || continue
        if udevadm info --query=property --name="$_d" 2>/dev/null | grep -q '^ID_BUS=usb$'; then
          _arduino_dev="$_d"
          break
        fi
      done
      if [[ -z "$_arduino_dev" ]]; then
        echo "[device-gogoping-sim] Arduino USB device 못 찾음 — sim 만 진행 (camera_pan 없이)" >&2
      else
        mapfile -t _ids < <(udevadm info -a -n "$_arduino_dev" 2>/dev/null | awk -F'==' '
          $1 ~ /ATTRS\{idVendor\}/  && !v { gsub(/"/, "", $2); v=$2 }
          $1 ~ /ATTRS\{idProduct\}/ && !p { gsub(/"/, "", $2); p=$2 }
          $1 ~ /ATTRS\{serial\}/    && !s { gsub(/"/, "", $2); s=$2 }
          END { print v; print p; print s }
        ')
        _v="${_ids[0]:-}"; _p="${_ids[1]:-}"; _s="${_ids[2]:-}"
        if [[ -z "$_v" || -z "$_p" ]]; then
          echo "[device-gogoping-sim] 경고: $_arduino_dev 의 vendor/product 추출 실패" >&2
        else
          if [[ -n "$_s" ]]; then
            _rule='SUBSYSTEM=="tty", ATTRS{idVendor}=="'"$_v"'", ATTRS{idProduct}=="'"$_p"'", ATTRS{serial}=="'"$_s"'", SYMLINK+="arduino-camera", MODE="0660", GROUP="dialout"'
          else
            _rule='SUBSYSTEM=="tty", ATTRS{idVendor}=="'"$_v"'", ATTRS{idProduct}=="'"$_p"'", SYMLINK+="arduino-camera", MODE="0660", GROUP="dialout"'
          fi
          echo "[device-gogoping-sim] $_arduino_dev ($_v:$_p${_s:+, serial=$_s}) → /etc/udev/rules.d/99-arduino-camera.rules"
          echo "$_rule" | sudo tee /etc/udev/rules.d/99-arduino-camera.rules >/dev/null
          sudo udevadm control --reload
          sudo udevadm trigger
          sleep 0.5
          if [[ -e /dev/arduino-camera ]]; then
            echo "[device-gogoping-sim] /dev/arduino-camera ready"
          else
            echo "[device-gogoping-sim] 경고: udev rule 추가 후에도 symlink 안 생김 — Arduino 재연결 후 재실행" >&2
          fi
        fi
      fi
    fi

    # 시연/디버그 — 환경변수 → ros-args. gogoping_modes 노드의 IdleTimeout/Battery/Health
    # monitor 들이 declare_parameter 로 받음 (utils/safety_flags.py).
    MODES_ARGS=""
    if [[ -n "${NO_BATTERY_SAFETY:-}" || -n "${NO_ERROR_SAFETY:-}" ]]; then
      MODES_ARGS="--ros-args"
      [[ -n "${NO_BATTERY_SAFETY:-}" ]] && MODES_ARGS+=" -p disable_battery_safety:=true"
      [[ -n "${NO_ERROR_SAFETY:-}" ]]   && MODES_ARGS+=" -p disable_error_safety:=true"
      echo "[device-gogoping-sim] modes 인자: $MODES_ARGS"
    fi

    # GOGOPING_MAP / GOGOPING_WORLD env 로 PGM·Gazebo world 후보 swap 가능 —
    # ~/pingdergarten-maps/cand_XX/{map.yaml,world.sdf} 같은 외부 후보 디렉토리를 빌드 없이 테스트.
    # 미지정 시 sim.launch.py 의 default (install/share 안 map.yaml + pingdergarten.world) 사용.
    # GOGOPING_SPAWN_X/Y/Z/YAW 로 Pinky 스폰 위치 override (m, rad). PGM 의 origin 좌표계 기준.
    SIM_LAUNCH_ARGS=""
    if [[ -n "${GOGOPING_MAP:-}" ]]; then
      SIM_LAUNCH_ARGS+=" map:=$GOGOPING_MAP"
      echo "[device-gogoping-sim] GOGOPING_MAP=$GOGOPING_MAP"
    fi
    if [[ -n "${GOGOPING_WORLD:-}" ]]; then
      SIM_LAUNCH_ARGS+=" world:=$GOGOPING_WORLD"
      echo "[device-gogoping-sim] GOGOPING_WORLD=$GOGOPING_WORLD"
    fi
    if [[ -n "${GOGOPING_SPAWN_X:-}" ]]; then
      SIM_LAUNCH_ARGS+=" spawn_x:=$GOGOPING_SPAWN_X"
      echo "[device-gogoping-sim] GOGOPING_SPAWN_X=$GOGOPING_SPAWN_X"
    fi
    if [[ -n "${GOGOPING_SPAWN_Y:-}" ]]; then
      SIM_LAUNCH_ARGS+=" spawn_y:=$GOGOPING_SPAWN_Y"
      echo "[device-gogoping-sim] GOGOPING_SPAWN_Y=$GOGOPING_SPAWN_Y"
    fi
    if [[ -n "${GOGOPING_SPAWN_Z:-}" ]]; then
      SIM_LAUNCH_ARGS+=" spawn_z:=$GOGOPING_SPAWN_Z"
      echo "[device-gogoping-sim] GOGOPING_SPAWN_Z=$GOGOPING_SPAWN_Z"
    fi
    if [[ -n "${GOGOPING_SPAWN_YAW:-}" ]]; then
      SIM_LAUNCH_ARGS+=" spawn_yaw:=$GOGOPING_SPAWN_YAW"
      echo "[device-gogoping-sim] GOGOPING_SPAWN_YAW=$GOGOPING_SPAWN_YAW"
    fi

    # tmux 3.4 의 server idle 종료 회피: sleep 으로 띄우고 respawn
    tmux new-session -d -s "$SESSION" -x 200 -y 50 -n gazebo \
      -c "$REPO_ROOT" "sleep infinity"
    tmux set-option -t "$SESSION" -g remain-on-exit on
    tmux respawn-pane -k -t "$SESSION:gazebo" -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_bringup sim.launch.py$SIM_LAUNCH_ARGS"

    # window 1: graph-router (vertex 그래프 + 다익스트라 + nav2 위임)
    tmux new-window -t "$SESSION" -n graph-router -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_navigation graph_router.launch.xml"

    # window 2: gogoping_modes (FSM + BT 본체 — /gogoping/state publish, /gogoping/set_goal server)
    tmux new-window -t "$SESSION" -n modes -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 run gogoping_modes gogoping_modes $MODES_ARGS"

    # window 3: sim-battery (sim 전용 — /gogoping/battery 1Hz + 디버그 slider srv)
    tmux new-window -t "$SESSION" -n sim-battery -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 run gogoping_bringup sim_battery_node --ros-args -r __ns:=/gogoping"

    # window 4: sim-teleport (sim 전용 — gz set_pose bridge for debug coord override)
    tmux new-window -t "$SESSION" -n sim-teleport -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 run gogoping_bringup sim_teleport_node --ros-args -r __ns:=/gogoping"

    # window 5: camera (USB 웹캠 → UDP MJPEG, sim 환경에서도 실 USB 카메라 사용 시).
    # /dev/video0 없으면 노드는 뜨지만 카메라 open 에러 — robot-web 의 CameraView 는
    # "영상 대기 중…" 으로 표시. CONTROL_SERVER_NAME 은 자기 자신 hostname (machine_ips.json 기준).
    _cam_w="${CAMERA_WIDTH:-640}"
    _cam_h="${CAMERA_HEIGHT:-480}"
    _cam_be="${CAMERA_BACKEND:-cv2}"   # sim 환경 default cv2 (외장 웹캠 호환성)
    _cam_server="${CONTROL_SERVER_NAME:-leekt}"   # 자기 hostname — machine_ips.json 에서 자기 IP
    tmux new-window -t "$SESSION" -n camera -c "$REPO_ROOT" \
      "$SOURCE_ENV && export CAMERA_WIDTH='$_cam_w' CAMERA_HEIGHT='$_cam_h' && exec ros2 launch gogoping_camera camera_stream.launch.py backend:=$_cam_be control_server:=$_cam_server"

    # window 6: camera-pan (Arduino MG995 ×2 pan/tilt 서보, /dev/arduino-camera 필요)
    # sim 환경에서도 실 Arduino USB 연결되어 있으면 동일하게 동작.
    # /dev/arduino-camera 없으면 노드는 뜨지만 serial open 에러 — admin UI 의 텔레옵
    # pan/tilt 슬라이더는 비-effect 로 동작 (REST 응답만 OK).
    tmux new-window -t "$SESSION" -n camera-pan -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_camera_pan camera_pan.launch.py"

    # window 7: rviz (map / TF / AMCL / costmap / plan 시각화)
    RVIZ_CONFIG="$REPO_ROOT/install/gogoping_navigation/share/gogoping_navigation/rviz/gogoping_view.rviz"
    tmux new-window -t "$SESSION" -n rviz -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec rviz2 -d $RVIZ_CONFIG"

    # 마우스 + status bar 설정
    tmux set-option -t "$SESSION" -g mouse on
    tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
    tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
    tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
    tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

    tmux select-window -t "$SESSION:gazebo"

    echo "[device-gogoping-sim] 세션 '$SESSION' 시작 — attach"
    echo "[device-gogoping-sim] ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-<unset>}"
    exec tmux attach -t "$SESSION"
    ;;
  down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      tmux kill-session -t "$SESSION"
      echo "[device-gogoping-sim] 세션 '$SESSION' 종료"
    else
      echo "[device-gogoping-sim] 세션 '$SESSION' 없음"
    fi
    # gz sim 의 server·gui 자식은 tmux SIGHUP 으로 회수되지 않아 명시 정리. SIGTERM → SIGKILL.
    _patterns=(
      "ros2 launch gogoping_bringup sim"
      "ros2 launch gogoping_navigation graph_router"
      "ros2 run gogoping_modes"
      "ros2 run gogoping_bringup sim_battery_node"
      "ros2 run gogoping_bringup sim_teleport_node"
      "gz sim"
      "ruby .*gz sim"
      "parameter_bridge"
      "ros_gz_image"
      "robot_state_publisher"
      "sim_status_publisher"
      "sim_battery_node"
      "sim_teleport_node"
      "rviz2"
    )
    for p in "${_patterns[@]}"; do
      pkill -TERM -f "$p" 2>/dev/null || true
    done
    sleep 0.5
    for p in "${_patterns[@]}"; do
      pkill -KILL -f "$p" 2>/dev/null || true
    done
    echo "[device-gogoping-sim] 가제보·브리지 잔여 프로세스 정리 완료"
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[device-gogoping-sim] '$SESSION' 실행 중"
      tmux list-windows -t "$SESSION"
    else
      echo "[device-gogoping-sim] '$SESSION' 없음"
    fi
    ;;
  *)
    echo "usage: $0 [up|down|status]" >&2
    exit 2
    ;;
esac
