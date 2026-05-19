#!/usr/bin/env bash
# scripts/device-gogoping-laptop.sh — GogoPing 노트북에서 실행하는 ROS 노드 묶음.
#
# 분산 배포 모델 (gogoping-controller/docs/gogoping-file-structure.md):
#   라즈베리파이 — 모터·센서 (vicpinky_bringup / sllidar / camera UDP / camera_pan)
#   노트북       — Nav2·modes·vision (본 스크립트)
#
# 동작:
#   - tmux 세션 'gogoping-laptop' 안에 window 3개:
#       graph-router : gogoping_navigation graph_router.launch.xml
#                      (vertex 그래프 + 다익스트라 + nav2 위임)
#       localization : gogoping_navigation localization_real.launch.xml
#                      (map_server + AMCL + lifecycle_manager). /map + /amcl_pose +
#                      map → odom TF 발행. map_boundary_monitor / PoseSubscriber 가 사용.
#       modes        : gogoping_modes (FSM + BT 본체 — /gogoping/state publish,
#                      /gogoping/set_goal service. control-server 가 이 둘로 connect.)
#
# 향후 추가될 window:
#   - nav2-full : planner + controller + bt_navigator (자율 주행) — 추후
#   - vision    : 사람 추적 / face matching / YOLO 추론 (laptop 노트북 쪽 NPU/GPU 사용)
#
# 사용:
#   scripts/device-gogoping-laptop.sh           # 세션 시작·attach (이미 떠있으면 attach)
#   scripts/device-gogoping-laptop.sh down      # tmux 세션 종료 + 잔여 프로세스 정리
#   scripts/device-gogoping-laptop.sh status    # 세션 상태
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

    # multicast 차단/미동작 환경에서 ROS 2 DDS discovery 를 unicast 로 우회.
    # ROS_PEER_HOST env (사용자 .zshrc 에 상대 머신 hostname) 의 hostname 을
    # shared/machine_ips.json 에서 IP lookup → Fast DDS XML profile 동적 생성.
    # 예: laptop .zshrc 에 `export ROS_PEER_HOST=vic` → Pi unicast 발견.
    MACHINE_IPS="$REPO_ROOT/shared/machine_ips.json"
    if [[ -n "${ROS_PEER_HOST:-}" ]] && [[ -f "$MACHINE_IPS" ]] && command -v jq &>/dev/null; then
      _peer_ips=()
      _IFS_orig="$IFS"; IFS=','
      for _host in $ROS_PEER_HOST; do
        _host="${_host// /}"
        [[ -z "$_host" ]] && continue
        _ip=$(jq -r ".${_host}.ip // empty" "$MACHINE_IPS" 2>/dev/null)
        if [[ -n "$_ip" ]]; then
          _peer_ips+=("$_ip")
        else
          echo "[device-gogoping-laptop] machine_ips.json 에 '$_host' 없음 — 건너뜀" >&2
        fi
      done
      IFS="$_IFS_orig"
      if [[ ${#_peer_ips[@]} -gt 0 ]]; then
        _domain="${ROS_DOMAIN_ID:-0}"
        _port=$(( 7400 + 250 * _domain ))
        _xml_path="/tmp/fastdds_peers_${USER}_${_domain}.xml"
        {
          echo '<?xml version="1.0" encoding="UTF-8" ?>'
          echo '<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">'
          echo '  <participant profile_name="participant_default" is_default_profile="true">'
          echo '    <rtps><builtin><initialPeersList>'
          for _ip in "${_peer_ips[@]}"; do
            echo "      <locator><udpv4><address>$_ip</address><port>$_port</port></udpv4></locator>"
          done
          echo '    </initialPeersList></builtin></rtps>'
          echo '  </participant>'
          echo '</profiles>'
        } > "$_xml_path"
        export FASTRTPS_DEFAULT_PROFILES_FILE="$_xml_path"
        echo "[device-gogoping-laptop] Fast DDS profile: $_xml_path (peers: ${_peer_ips[*]}, port: $_port)"
      fi
    fi

    SOURCE_ENV="source $ROS_SETUP && source $WS_SETUP"

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

    # CAMERA_DEVICE 결정 — 우선순위: caller env (존재할 때) → /dev/usb-webcam udev symlink → 자동 탐지.
    if [[ -n "${CAMERA_DEVICE:-}" && ! -e "$CAMERA_DEVICE" ]]; then
      echo "[device-gogoping-laptop] 경고: CAMERA_DEVICE=$CAMERA_DEVICE 가 존재하지 않음 — 자동 감지로 fallback" >&2
      unset CAMERA_DEVICE
    fi
    if [[ -z "${CAMERA_DEVICE:-}" ]]; then
      if [[ -e /dev/usb-webcam ]]; then
        CAMERA_DEVICE=/dev/usb-webcam
        echo "[device-gogoping-laptop] CAMERA_DEVICE=/dev/usb-webcam (udev symlink)"
      else
        # 자동 탐지: USB bus + MJPG 지원하는 /dev/video* 중 첫 device.
        # 내장 카메라 (Bison/Chicony 등) 도 ID_BUS=usb 라 모델명 키워드로 외장만 필터.
        _detected=""
        for _n in 0 1 2 3 4 5 6 7 8 9; do
          _dev="/dev/video$_n"
          [[ -e "$_dev" ]] || continue
          _props=$(udevadm info --query=property --name="$_dev" 2>/dev/null)
          echo "$_props" | grep -q '^ID_BUS=usb$' || continue
          if echo "$_props" | grep -qiE '^(ID_USB_MODEL|ID_MODEL)=.*(integrated|built.?in|internal)'; then
            continue
          fi
          v4l2-ctl --device "$_dev" --list-formats 2>/dev/null | grep -qw 'MJPG' || continue
          _detected="$_dev"
          break
        done
        if [[ -n "$_detected" ]]; then
          CAMERA_DEVICE="$_detected"
          echo "[device-gogoping-laptop] CAMERA_DEVICE=$CAMERA_DEVICE (auto-detected, USB MJPG)"
        else
          echo "[device-gogoping-laptop] 경고: USB MJPG 웹캠 자동 감지 실패 — camera launch 가 실패할 수 있음" >&2
          echo "[device-gogoping-laptop]   해결: CAMERA_DEVICE=/dev/videoN 명시 또는 scripts/setup_usb_webcam.sh --apply (udev 룰)" >&2
          CAMERA_DEVICE=/dev/usb-webcam
        fi
      fi
      export CAMERA_DEVICE
    else
      echo "[device-gogoping-laptop] CAMERA_DEVICE=$CAMERA_DEVICE (caller env)"
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
    tmux new-window -t "$SESSION" -n localization -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_navigation localization_real.launch.xml"

    # window 2: gogoping_modes (FSM + BT 본체)
    tmux new-window -t "$SESSION" -n modes -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 run gogoping_modes gogoping_modes"

    # window 3: camera — USB 웹캠 → UDP MJPEG (SR-CAM-001).
    # backend=cv2 default: 외장 웹캠 native MJPEG quality 높아 v4l2 직송 시 frame > 65.4KB drop.
    #   cv2 는 decode 후 q=60 재인코딩 (~30KB). 다른 카메라는 CAMERA_BACKEND=v4l2 로 override.
    # $CAMERA_* 는 outer shell 에서 치환 (escape 하면 tmux 안에서 unset).
    _cam_w="${CAMERA_WIDTH:-640}"
    _cam_h="${CAMERA_HEIGHT:-480}"
    _cam_be="${CAMERA_BACKEND:-cv2}"
    tmux new-window -t "$SESSION" -n camera -c "$REPO_ROOT" \
      "$SOURCE_ENV && export CAMERA_DEVICE='$CAMERA_DEVICE' CAMERA_WIDTH='$_cam_w' CAMERA_HEIGHT='$_cam_h' && exec ros2 launch gogoping_camera camera_stream.launch.py backend:=$_cam_be"

    # window 4: camera-pan — Arduino 시리얼 (MG995 ×2 pan/tilt, /dev/arduino-camera 필요)
    tmux new-window -t "$SESSION" -n camera-pan -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_camera_pan camera_pan.launch.py"

    # 마우스 + status bar 설정
    tmux set-option -t "$SESSION" -g mouse on
    tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
    tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
    tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
    tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

    tmux select-window -t "$SESSION:modes"

    echo "[device-gogoping-laptop] 세션 '$SESSION' 시작 — attach"
    echo "[device-gogoping-laptop] ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-<unset>}"
    echo "[device-gogoping-laptop] 하단 status bar 의 'graph-router / localization / modes / camera / camera-pan' 클릭으로 전환"
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
      "ros2 run gogoping_modes"
      "ros2 launch gogoping_camera camera_stream"
      "ros2 launch gogoping_camera_pan camera_pan"
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
