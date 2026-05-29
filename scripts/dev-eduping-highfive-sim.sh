#!/usr/bin/env zsh
# Sim stack for EduPing high-five: MoveIt IK + sim_twin + highfive_node.
#
# ROS_DOMAIN_ID — 호출 셸 환경 그대로 사용 (본 스크립트는 export/설정 안 함).
# 팀원마다 할당 ID 가 다름 (201~219, 루트 CLAUDE.md) — zshrc 등에서 본인 ID 만 설정.
# control-service(eduping bridge) · sim · RViz · run_server control window 가 **같은 ID** 여야 통신함.
#
# Prereqs:
#   scripts/run_server.sh  (control :8000 + streaming :8100)
#   D435 (뎁스카메라 뷰): scripts/device-eduping-d435.sh base  (또는 ros2 launch eduarm eduping_d435_base.launch.py)
#   cd service/web-service/robot-web && npm run dev
#
# UI: EduPing → 뎁스카메라 뷰 → ✋ ON → hold hand in 0.3–1.5 m
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONTROLLER="$REPO_ROOT/controller/eduping-controller"

if [[ ! -f /opt/ros/jazzy/setup.zsh ]]; then
  echo "[highfive-sim] ROS Jazzy not found at /opt/ros/jazzy/setup.zsh" >&2
  exit 1
fi

if [[ ! -f "$CONTROLLER/install/setup.zsh" ]]; then
  echo "[highfive-sim] colcon install missing — run:" >&2
  echo "  cd $CONTROLLER && source /opt/ros/jazzy/setup.zsh && colcon build --symlink-install" >&2
  exit 1
fi

# ROS/colcon setup.zsh reference AMENT_TRACE_SETUP_FILES, COLCON_TRACE, etc.
# that are unset on a fresh shell — `set -u` would abort before PATH is updated.
set +u
source /opt/ros/jazzy/setup.zsh
source "$CONTROLLER/install/setup.zsh"
set -u

if [[ -z "${ROS_DOMAIN_ID:-}" ]]; then
  echo "[highfive-sim] ⚠ ROS_DOMAIN_ID unset — 본인 할당 ID 를 zshrc 등에서 export 후 재실행 (미설정 시 domain 0)" >&2
else
  echo "[highfive-sim] ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
fi
if ! curl -sf http://localhost:8000/api/eduping/health >/dev/null 2>&1; then
  echo "[highfive-sim] ⚠ control-service 미응답 — scripts/run_server.sh (control window 도 같은 ROS_DOMAIN_ID)" >&2
fi
if command -v curl >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  depth_seq="$(curl -sf http://localhost:8100/health 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin).get('depth', {}).get('latest_seq', {})
    v = d.get('eduping')
    print(v if v is not None else '', end='')
except Exception:
    pass
" 2>/dev/null || true)"
  if [[ -z "$depth_seq" ]]; then
    echo "[highfive-sim] ⚠ D435 depth producer 없음 — 뎁스카메라 뷰: scripts/device-eduping-d435.sh base" >&2
  fi
fi
echo "[highfive-sim] Launching highfive_sim (move_group + sim_twin + highfive_node)…"
exec ros2 launch eduarm highfive_sim.launch.py
