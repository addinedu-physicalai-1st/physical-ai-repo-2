#!/usr/bin/env bash
# scripts/device-gogoping-pi.sh — GogoPing 라즈베리파이에서 실행하는 ROS 노드 묶음.
#
# 분산 배포 모델 (gogoping-controller/docs/gogoping-file-structure.md):
#   라즈베리파이 — 모터·센서·카메라 시리얼 (본 스크립트)
#   노트북       — Nav2·modes·vision (scripts/device-gogoping-laptop.sh)
#
# 두 머신은 같은 ROS_DOMAIN_ID 로 통신. ROS_DOMAIN_ID 환경변수는 양쪽 셸에서 일치하게.
#
# 동작:
#   - tmux 세션 'gogoping-pi' 안에 window 2개 (bringup / camera-pan)
#   - bringup    : gogoping_bringup pi.launch.py
#                  (모터 + sllidar_c1 + URDF + laser_filter + 카메라 UDP 송출 SR-CAM-001,
#                   모두 '/gogoping' namespace 안)
#   - camera-pan : gogoping_camera_pan camera_pan.launch.py (Arduino 시리얼 카메라 팬)
#   - 한 화면엔 1개 window 만 표시. 하단 status bar 의 window 이름 클릭으로 전환
#
# graph-router 와 gogoping_modes 는 laptop 측에서 별도 띄움 — device-gogoping-laptop.sh.
#
# 사용:
#   scripts/device-gogoping-pi.sh           # 세션 시작·attach (이미 떠있으면 attach)
#   scripts/device-gogoping-pi.sh down      # tmux 세션 종료
#   scripts/device-gogoping-pi.sh status    # 세션 상태 + window 목록
#
# 의존:
#   - tmux
#   - /opt/ros/jazzy 설치
#   - repo root 에서 colcon build 완료 (./install/setup.bash 존재)
#   - ROS_DOMAIN_ID 는 호출 셸 환경 그대로 사용 (export 안 함)
#
# 환경변수 (bringup 안 카메라 송출 노드에 전파):
#   CONTROL_SERVER_NAME  shared/machine_ips.json 의 hostname (기본 'tonyno')
#   기타 인자 — pi.launch.py 가 gogoping_camera launch 를 include 함.
#   상세: controller/gogoping-controller/src/gogoping/gogoping_camera/CLAUDE.md
#
# 단축키 (tmux):
#   - 마우스로 하단 status bar 의 window 이름 클릭 → 전환
#   - Ctrl+B 다음 0/1 → window 번호로 전환
#   - Ctrl+B 다음 D → detach (백그라운드 유지)
set -euo pipefail

SESSION="gogoping-pi"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-up}"

ROS_SETUP="/opt/ros/jazzy/setup.zsh"
WS_SETUP="$REPO_ROOT/install/local_setup.zsh"

if ! command -v tmux &>/dev/null; then
  echo "[device-gogoping-pi] tmux 가 설치되어 있지 않습니다 (sudo apt install tmux)" >&2
  exit 1
fi

case "$ACTION" in
  up|"")
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[device-gogoping-pi] 세션 '$SESSION' 이미 떠있음 — attach"
      exec tmux attach -t "$SESSION"
    fi

    if [[ ! -f "$ROS_SETUP" ]]; then
      echo "[device-gogoping-pi] ROS Jazzy 가 설치되어 있지 않습니다 ($ROS_SETUP 없음)" >&2
      exit 1
    fi
    if [[ ! -f "$WS_SETUP" ]]; then
      echo "[device-gogoping-pi] workspace 가 빌드되어 있지 않습니다." >&2
      echo "[device-gogoping-pi]   cd $REPO_ROOT && colcon build --symlink-install" >&2
      exit 1
    fi

    # multicast 차단/미동작 환경에서 ROS 2 DDS discovery 를 unicast 로 우회.
    # ROS_PEER_HOST env (사용자 .zshrc 에 상대 머신 hostname 콤마 구분) 의 hostname 들을
    # shared/machine_ips.json 에서 IP lookup → Fast DDS XML profile 동적 생성.
    # 예: Pi .zshrc 에 `export ROS_PEER_HOST=leekt,tonyno` → 두 laptop 모두 unicast 발견.
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
          echo "[device-gogoping-pi] machine_ips.json 에 '$_host' 없음 — 건너뜀" >&2
        fi
      done
      IFS="$_IFS_orig"
      if [[ ${#_peer_ips[@]} -gt 0 ]]; then
        # Fast DDS PDP multicast meta port = 7400 + 250 * domain
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
        echo "[device-gogoping-pi] Fast DDS profile: $_xml_path (peers: ${_peer_ips[*]}, port: $_port)"
      fi
    fi

    SOURCE_ENV="source $ROS_SETUP && source $WS_SETUP"

    # tmux 3.4 의 server idle 종료를 피하기 위해 첫 session 을 sleep 으로 띄우고
    # remain-on-exit 적용 후 실제 명령으로 respawn 한다.
    # remain-on-exit on: 프로세스 종료해도 window 유지 (에러 보고 디버깅 가능)
    tmux new-session -d -s "$SESSION" -x 200 -y 50 -n bringup -c "$REPO_ROOT" "sleep infinity"
    tmux set-option -t "$SESSION" -g remain-on-exit on
    tmux respawn-pane -k -t "$SESSION:bringup" -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_bringup pi.launch.py"

    # window 1: camera-pan
    tmux new-window -t "$SESSION" -n camera-pan -c "$REPO_ROOT" \
      "$SOURCE_ENV && exec ros2 launch gogoping_camera_pan camera_pan.launch.py"

    # graph-router / gogoping_modes 는 laptop 측 (scripts/device-gogoping-laptop.sh) 에서 띄움.
    #
    # 카메라 UDP MJPEG 송출 (SR-CAM-001) 은 bringup 안에 IncludeLaunchDescription 으로 통합됨.
    # → pi.launch.py 가 gogoping_camera/launch/camera_stream.launch.py 호출.
    # → 별도 window 불필요. CONTROL_SERVER_NAME env 는 bringup window 에 전파.

    # 마우스 + status bar 설정 (window 이름 클릭으로 전환 가능)
    tmux set-option -t "$SESSION" -g mouse on
    tmux set-option -t "$SESSION" -g status-style 'bg=colour235,fg=colour250'
    tmux set-option -t "$SESSION" -g window-status-current-style 'bg=colour33,fg=white,bold'
    tmux set-option -t "$SESSION" -g window-status-format ' #I:#W '
    tmux set-option -t "$SESSION" -g window-status-current-format ' #I:#W '

    tmux select-window -t "$SESSION:bringup"

    echo "[device-gogoping-pi] 세션 '$SESSION' 시작 — attach"
    echo "[device-gogoping-pi] ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-<unset>}"
    echo "[device-gogoping-pi] CONTROL_SERVER_NAME=${CONTROL_SERVER_NAME:-tonyno (default)}"
    echo "[device-gogoping-pi] 하단 status bar 의 'bringup / camera-pan' 클릭으로 전환"
    echo "[device-gogoping-pi] graph-router + gogoping_modes 는 노트북에서: scripts/device-gogoping-laptop.sh"
    exec tmux attach -t "$SESSION"
    ;;
  down)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      tmux kill-session -t "$SESSION"
      echo "[device-gogoping-pi] 세션 '$SESSION' 종료"
    else
      echo "[device-gogoping-pi] 세션 '$SESSION' 없음"
    fi
    ;;
  status)
    if tmux has-session -t "$SESSION" 2>/dev/null; then
      echo "[device-gogoping-pi] '$SESSION' 실행 중"
      tmux list-windows -t "$SESSION"
    else
      echo "[device-gogoping-pi] '$SESSION' 없음"
    fi
    ;;
  *)
    echo "usage: $0 [up|down|status]" >&2
    exit 2
    ;;
esac
