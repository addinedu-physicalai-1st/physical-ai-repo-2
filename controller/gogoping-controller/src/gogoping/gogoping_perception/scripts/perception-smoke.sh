#!/usr/bin/env bash
# perception 회귀 스모크 — 합성 프레임으로 노드 기동 + device/hz 확인.
# 사용: bash perception-smoke.sh   (어디서든 실행 가능 — 경로 자동 계산)
# 주의: ROS setup 은 bash 전용 (zsh 에서 /opt/ros/jazzy/setup.bash 가 self-path 못 찾음).
set -u
# 스크립트 위치: .../gogoping_perception/scripts/ → 4단계 위가 gogoping-controller(install/ 보유)
WS="$(cd "$(dirname "$0")/../../../.." && pwd)"   # gogoping-controller 루트
PKG="$WS/src/gogoping/gogoping_perception"
CAM="$WS/src/gogoping/gogoping_camera"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-215}"

cleanup() {
  pkill -f perception_node 2>/dev/null
  pkill -f "topic pub /gogoping/state_str" 2>/dev/null
  pkill -f perception_shm_stub 2>/dev/null
  rm -f /dev/shm/gogoping_color_640 /dev/shm/gogoping_depth_640 /dev/shm/gogoping_meta
}
trap cleanup EXIT

PYTHONPATH="$CAM" /usr/bin/python3 "$PKG/scripts/perception_shm_stub.py" 40 &
sleep 1

LOG="$(mktemp)"
bash -c "source /opt/ros/jazzy/setup.bash; source '$WS/install/local_setup.bash'; \
  exec ros2 run gogoping_perception perception_node" > "$LOG" 2>&1 &
sleep 6
bash -c "source /opt/ros/jazzy/setup.bash; source '$WS/install/local_setup.bash'; \
  exec ros2 topic pub /gogoping/state_str std_msgs/msg/String '{data: GOTO}' -r 2" >/dev/null 2>&1 &
sleep 12

echo "=== device 로그 ==="; grep -E "Engines ready|device=" "$LOG" | tail -2
echo "=== person_proximity hz ==="
bash -c "source /opt/ros/jazzy/setup.bash; source '$WS/install/local_setup.bash'; \
  timeout 8 ros2 topic hz /gogoping/person_proximity" 2>&1 | tail -2
echo "=== PASS 기준: device=cuda:0 + hz 두 자릿수 ==="
