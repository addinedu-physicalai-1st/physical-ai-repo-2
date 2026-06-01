#!/usr/bin/env bash
# Show the OpenArm high-five in MuJoCo on demand.
#
# MuJoCo was removed from the default launch (run_server.sh / run_control.sh now use
# the lightweight sim_twin — sim demo finished). This re-attaches the MuJoCo physics
# viewer by respawning the existing 'highfive' tmux window with mujoco:=true, so
# mujoco_twin_node REPLACES sim_twin (one /joint_states publisher — no conflict).
# The browser depth view + high-five keep working; you also get the MuJoCo window.
#
# Usage:
#   scripts/run_server.sh                 # bring the stack up first (no MuJoCo)
#   scripts/show_mujoco_highfive.sh       # → MuJoCo viewer on the high-five
#   # to go back to no-MuJoCo: re-run the highfive window without the arg, e.g.
#   #   tmux respawn-window -k -t pingdergarten:highfive \
#   #     "bash -c 'source /opt/ros/jazzy/setup.bash; \
#   #       source <repo>/controller/eduping-controller/install/setup.bash; \
#   #       exec ros2 launch eduarm highfive_sim.launch.py'"
set -euo pipefail

SESSION="pingdergarten"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WS_SETUP="$REPO_ROOT/controller/eduping-controller/install/setup.bash"
: "${ROS_DOMAIN_ID:=203}"   # must match the rest of the stack (d435/control on 203)

if ! command -v tmux >/dev/null 2>&1; then
  echo "[show-mujoco] tmux 미설치." >&2; exit 1
fi
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "[show-mujoco] tmux 세션 '$SESSION' 없음 — 먼저 scripts/run_server.sh 실행하세요." >&2
  exit 1
fi
if [ ! -f "$WS_SETUP" ]; then
  echo "[show-mujoco] eduarm install 없음 ($WS_SETUP) — colcon build 먼저." >&2; exit 1
fi

tmux respawn-window -k -t "$SESSION:highfive" \
  "bash -c 'source /opt/ros/jazzy/setup.bash; source $WS_SETUP; \
     export ROS_DOMAIN_ID=$ROS_DOMAIN_ID; \
     exec ros2 launch eduarm highfive_sim.launch.py mujoco:=true'"

echo "[show-mujoco] highfive 창 → MuJoCo viewer (mujoco:=true, ROS_DOMAIN_ID=$ROS_DOMAIN_ID)."
echo "[show-mujoco] ~12s 후 GLFW 창이 뜹니다. browser 고배율(high-five)은 그대로 동작."
echo "[show-mujoco] MuJoCo 끄려면 highfive 창을 arg 없이 재실행 (sim_twin 으로 복귀)."
