#!/usr/bin/env bash
# scripts/device-gogoping-laptop.sh — GogoPing 노트북에서 실행하는 ROS 노드 묶음.
#
# 분산 배포 모델 (gogoping-controller/docs/gogoping-file-structure.md):
#   라즈베리파이 — 모터·센서 (vicpinky_bringup / sllidar)
#   노트북       — Nav2 + perception + follow + D435 camera + camera_pan
#
# 동작:
#   - tmux 세션 'gogoping-laptop' 안에 window 9개:
#       graph-router : gogoping_navigation graph_router.launch.xml
#                      (vertex 그래프 + 다익스트라 + nav2 위임)
#       localization : gogoping_navigation localization_real.launch.xml
#                      (map_server + AMCL + lifecycle_manager). /map + /amcl_pose +
#                      map → odom TF 발행. map_boundary_monitor / PoseSubscriber 가 사용.
#       nav2         : navigation_real.launch.xml (controller + planner + bt_navigator …)
#       modes        : gogoping_modes (FSM + BT 본체 — /gogoping/state publish,
#                      /gogoping/set_goal service. control-server 가 이 둘로 connect.)
#       camera       : D435 + WebRTC (gogoping_camera d435_webrtc_node, SR-CAM-001 후속).
#       camera-pan   : Arduino 시리얼 MG995 ×2 pan/tilt (gogoping_camera_pan).
#       perception   : gogoping_perception perception.launch.py — /camera/image_raw →
#                      YOLO + ByteTrack + ReID → /gogoping/tracking_state (5 Hz). GPU lazy-load.
#       follow       : gogoping_follow follow.launch.py — /gogoping/tracking_state + /scan →
#                      /cmd_vel (P 컨트롤 20 Hz).
#       rviz         : rviz2 -d gogoping_view.rviz (Map + TF + RobotModel + LaserScan 시각화)
#
# 사용:
#   scripts/device-gogoping-laptop.sh           # 세션 시작·attach (이미 떠있으면 attach)
#   scripts/device-gogoping-laptop.sh down      # tmux 세션 종료 + 잔여 프로세스 정리
#   scripts/device-gogoping-laptop.sh status    # 세션 상태
#
# 시연/디버그 환경변수 (gogoping_modes 노드에 ros-args 로 전달):
#   NO_BATTERY_SAFETY=1   BatteryLowMonitor 비활성 — 배터리 ≤20% 자동 RETURNING 차단
#   NO_ERROR_SAFETY=1     HardwareHealth / MapBoundary fault → ERROR 차단
# 예시: NO_BATTERY_SAFETY=1 NO_ERROR_SAFETY=1 scripts/device-gogoping-laptop.sh
#
# 의존:
#   - tmux
#   - /opt/ros/jazzy 설치
#   - repo root 에서 colcon build 완료 (./install/local_setup.zsh 존재)
#   - ROS_DOMAIN_ID 는 호출 셸 환경 그대로 사용 (export 안 함)
#     같은 도메인의 Pi (device-gogoping-pi.sh) 와 ROS_DOMAIN_ID 일치해야 통신
#
# 단축키 (tmux):
#   - 마우스로 하단 status bar 의 window 이름 클릭 → 전환
#   - Ctrl+B 다음 0/1 → window 번호로 전환
#   - Ctrl+B 다음 D → detach (백그라운드 유지)
set -euo pipefail

SESSION="gogoping-laptop"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-up}"

ROS_SETUP="/opt/ros/jazzy/setup.zsh"
WS_SETUP="$REPO_ROOT/install/local_setup.zsh"

if ! command -v tmux &>/dev/null; then
  echo "[device-gogoping-laptop] tmux 가 설치되어 있지 않습니다 (sudo apt install tmux)" >&2
  exit 1
fi

case "$ACTION" in
  up|"")
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      _dead=$(tmux list-panes -t "$SESSION:graph-router" -F '#{pane_dead}' 2>/dev/null | head -1)
      if [[ "$_dead" == "1" ]]; then
        echo "[device-gogoping-laptop] 이전 세션의 pane 이 죽어있음 — 정리 후 재시작"
        tmux kill-session -t "$SESSION"
      else
        echo "[device-gogoping-laptop] 세션 '$SESSION' 이미 떠있음 — attach"
        exec tmux attach -t "$SESSION"
      fi
    fi

    if [[ ! -f "$ROS_SETUP" ]]; then
      echo "[device-gogoping-laptop] ROS Jazzy 가 설치되어 있지 않습니다 ($ROS_SETUP 없음)" >&2
      exit 1
    fi
    if [[ ! -f "$WS_SETUP" ]]; then
      echo "[device-gogoping-laptop] workspace 가 빌드되어 있지 않습니다." >&2
      echo "[device-gogoping-laptop]   cd $REPO_ROOT && colcon build --symlink-install" >&2
      exit 1
    fi

    # DDS discovery 는 ~/.zshrc 의 RMW_IMPLEMENTATION + CYCLONEDDS_URI (cyclonedds peers)
    # 로 처리한다. multicast 차단 환경에선 zshrc 의 <Peers> 안 IP 가 unicast 발견 담당.

    SOURCE_ENV="source $ROS_SETUP && source $WS_SETUP"

    # 시연/디버그 — 환경변수 → ros-args. gogoping_modes 노드의 monitor 들이 declare_parameter
    # 로 받음 (utils/safety_flags.py).
    # cmd_vel 을 safety_filter 경유시키기 위해 remap 고정 설정.
    MODES_ARGS="--ros-args -r /gogoping/cmd_vel:=/gogoping/cmd_vel_raw"
    if [[ -n "${NO_BATTERY_SAFETY:-}" || -n "${NO_ERROR_SAFETY:-}" ]]; then
      [[ -n "${NO_BATTERY_SAFETY:-}" ]] && MODES_ARGS+=" -p disable_battery_safety:=true"
      [[ -n "${NO_ERROR_SAFETY:-}" ]]   && MODES_ARGS+=" -p disable_error_safety:=true"
      echo "[device-gogoping-laptop] modes 인자: $MODES_ARGS"
    fi

    # /dev/arduino-camera (camera-pan 서보용 symlink) 없으면 udev rule 자동 install — 1회만, sudo 묻음.
    # 실패해도 진행 — camera-pan window 에서 serial open 에러로 표시됨.
    if [[ ! -e /dev/arduino-camera ]]; then
      echo "[device-gogoping-laptop] /dev/arduino-camera 없음 — udev rule 자동 install (sudo 묻음)"
      _arduino_dev=""
      for _d in /dev/ttyACM* /dev/ttyUSB*; do
        [[ -e "$_d" ]] || continue
        if udevadm info --query=property --name="$_d" 2>/dev/null | grep -q '^ID_BUS=usb$'; then
          _arduino_dev="$_d"
          break
        fi
      done
      if [[ -z "$_arduino_dev" ]]; then
        echo "[device-gogoping-laptop] 경고: USB Arduino device 못 찾음 — 연결 확인 후 재실행" >&2
      else
        mapfile -t _ids < <(udevadm info -a -n "$_arduino_dev" 2>/dev/null | awk -F'==' '
          $1 ~ /ATTRS\{idVendor\}/  && !v { gsub(/"/, "", $2); v=$2 }
          $1 ~ /ATTRS\{idProduct\}/ && !p { gsub(/"/, "", $2); p=$2 }
          $1 ~ /ATTRS\{serial\}/    && !s { gsub(/"/, "", $2); s=$2 }
          END { print v; print p; print s }
        ')
        _v="${_ids[0]:-}"; _p="${_ids[1]:-}"; _s="${_ids[2]:-}"
        if [[ -z "$_v" || -z "$_p" ]]; then
          echo "[device-gogoping-laptop] 경고: $_arduino_dev 의 vendor/product 추출 실패" >&2
        else
          if [[ -n "$_s" ]]; then
            _rule='SUBSYSTEM=="tty", ATTRS{idVendor}=="'"$_v"'", ATTRS{idProduct}=="'"$_p"'", ATTRS{serial}=="'"$_s"'", SYMLINK+="arduino-camera", MODE="0660", GROUP="dialout"'
          else
            _rule='SUBSYSTEM=="tty", ATTRS{idVendor}=="'"$_v"'", ATTRS{idProduct}=="'"$_p"'", SYMLINK+="arduino-camera", MODE="0660", GROUP="dialout"'
          fi
          echo "[device-gogoping-laptop] $_arduino_dev ($_v:$_p${_s:+, serial=$_s}) → /etc/udev/rules.d/99-arduino-camera.rules"
          echo "$_rule" | sudo tee /etc/udev/rules.d/99-arduino-camera.rules >/dev/null
          sudo udevadm control --reload
          sudo udevadm trigger
          sleep 0.5
          if [[ -e /dev/arduino-camera ]]; then
            echo "[device-gogoping-laptop] /dev/arduino-camera ready"
          else
            echo "[device-gogoping-laptop] 경고: udev trigger 후 /dev/arduino-camera 안 생성됨 — 권한 또는 rule 매칭 문제" >&2
          fi
        fi
      fi
    fi

    # tmux 3.4 의 server idle 종료 회피: sleep 으로 띄우고 respawn
    tmux new-session -d -s "$SESSION" -x 200 -y 50 -n graph-router \
      -c "$REPO_ROOT" "sleep infinity"
    tmux set-option -t "$SESSION" -g remain-on-exit on
    # graph-router: base_frame:=base_link — Pi 가 unprefixed frame (base_link) 발행하므로 매칭.
    # sim 은 launch.xml default ('gogoping/base_link') 그대로 (이 스크립트 안 거침).
    tmux respawn-pane -k -t "$SESSION:graph-router" -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_navigation graph_router.launch.xml base_frame:=base_link"

    # window 1: localization (map_server + AMCL + lifecycle_manager_localization)
    # map:= 로 default (real_lidar_map.yaml) 대신 map.yaml (도면 + SLAM 정합) 사용.
    # GOGOPING_MAP env 로 후보 PGM swap 가능 (예: ~/pingdergarten-maps/cand_03/map.yaml).
    LOCALIZATION_MAP="${GOGOPING_MAP:-$REPO_ROOT/install/gogoping_navigation/share/gogoping_navigation/maps/map.yaml}"
    echo "[device-gogoping-laptop] LOCALIZATION_MAP=$LOCALIZATION_MAP"
    tmux new-window -t "$SESSION" -n localization -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_navigation localization_real.launch.xml map:=$LOCALIZATION_MAP"

    # window 2: nav2 navigation stack (controller + planner + bt_navigator + behavior +
    # waypoint_follower + velocity_smoother + lifecycle_manager_navigation).
    # localization 의 /amcl_pose + map → odom TF 위에서 동작.
    # admin-ui 의 graph_router 가 /navigate_through_poses action 호출 → 실제 이동.
    tmux new-window -t "$SESSION" -n nav2 -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_navigation navigation_real.launch.xml"

    # window 3: gogoping_modes (FSM + BT 본체)
    tmux new-window -t "$SESSION" -n modes -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 run gogoping_modes gogoping_modes $MODES_ARGS"

    # window 3: camera — D435 + WebRTC (H.264 NVENC), SR-CAM-001 후속.
    # camera_stream.launch.py 가 d435_webrtc_node 띄움 — robot-web(LAN P2P) + admin-ui 로 분배.
    # perception 은 동시에 POSIX shm 으로 raw frame 읽음 (depth fusion).
    # 상세: controller/gogoping-controller/src/gogoping/gogoping_camera/CLAUDE.md
    tmux new-window -t "$SESSION" -n camera -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_camera camera_stream.launch.py"

    # window 4: camera-pan — Arduino 시리얼 (MG995 ×2 pan/tilt, /dev/arduino-camera 필요)
    tmux new-window -t "$SESSION" -n camera-pan -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_camera_pan camera_pan.launch.py"

    # window 4b: camera-track — tracking_state bbox → pan/tilt servo (auto centering).
    # servo_bridge 가 먼저 떠 있어야 cmd_pan/cmd_tilt 가 수신됨.
    tmux new-window -t "$SESSION" -n camera-track -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_camera_pan camera_tracking.launch.py"

    # window 5: perception — /camera/image_raw → YOLO + ByteTrack + ReID → /gogoping/tracking_state.
    # GPU lazy-load on first /gogoping/follow_target. follow_node 는 이 토픽만 subscribe.
    tmux new-window -t "$SESSION" -n perception -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_perception perception.launch.py"

    # window 6: follow — /gogoping/tracking_state + /scan 구독 → /cmd_vel (20 Hz P 컨트롤).
    tmux new-window -t "$SESSION" -n follow -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_follow follow.launch.py"

    # window 7: rviz2 (Map + TF + RobotModel + LaserScan)
    # config 는 install/share 의 symlink (--symlink-install 가정).
    RVIZ_CONFIG="$REPO_ROOT/install/gogoping_navigation/share/gogoping_navigation/rviz/gogoping_view.rviz"
    tmux new-window -t "$SESSION" -n rviz -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec rviz2 -d $RVIZ_CONFIG"

    # 마우스 + status bar 설정
    tmux set-option -t "$SESSION" -g mouse on
    tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
    tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
    tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
    tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

    tmux select-window -t "$SESSION:modes"

    echo "[device-gogoping-laptop] 세션 '$SESSION' 시작 — attach"
    echo "[device-gogoping-laptop] ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-<unset>}"
    echo "[device-gogoping-laptop] 하단 status bar 의 'graph-router / localization / nav2 / modes / camera / camera-pan / perception / follow / rviz' 클릭으로 전환"
    exec tmux attach -t "$SESSION"
    ;;
  down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      tmux kill-session -t "$SESSION"
      echo "[device-gogoping-laptop] 세션 '$SESSION' 종료"
    else
      echo "[device-gogoping-laptop] 세션 '$SESSION' 없음"
    fi
    _patterns=(
      "ros2 launch gogoping_navigation graph_router"
      "ros2 launch gogoping_navigation localization_real"
      "ros2 launch gogoping_navigation navigation_real"
      "ros2 run gogoping_modes"
      "ros2 launch gogoping_camera camera_stream"
      "ros2 launch gogoping_camera_pan camera_pan"
      "ros2 launch gogoping_perception perception"
      "ros2 launch gogoping_follow follow"
      "rviz2 -d .*gogoping_view"
    )
    for p in "${_patterns[@]}"; do
      pkill -TERM -f "$p" 2>/dev/null || true
    done
    sleep 0.5
    for p in "${_patterns[@]}"; do
      pkill -KILL -f "$p" 2>/dev/null || true
    done
    echo "[device-gogoping-laptop] 잔여 프로세스 정리 완료"
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[device-gogoping-laptop] '$SESSION' 실행 중"
      tmux list-windows -t "$SESSION"
    else
      echo "[device-gogoping-laptop] '$SESSION' 없음"
    fi
    ;;
  *)
    echo "usage: $0 [up|down|status]" >&2
    exit 2
    ;;
esac
