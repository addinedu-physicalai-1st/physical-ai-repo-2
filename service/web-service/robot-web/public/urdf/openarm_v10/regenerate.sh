#!/usr/bin/env bash
# Regenerate openarm.urdf from the upstream xacro (`openarm_description` submodule).
#
# Why this exists: the frontend (three.js URDFLoader in OpenarmViewer.vue) loads a
# *static* URDF, not the xacro. If the xacro is updated (e.g. D435 mount added), the
# static URDF goes stale until someone runs this script. The OpenarmViewer relies on
# `d435_depth_optical_frame` link being present for `useDepthCloudInScene` to attach
# the point cloud, so the regen is load-bearing for the 뎁스카메라 뷰 mode.
#
# Frontend-only overrides (do NOT edit the submodule xacro to set these):
#   d435_mount_xyz="0.05 0.0 0.62"   # 3D-printed body armor 바로 아래 (어깨 z=0.698)
#
# Usage:
#   bash service/web-service/robot-web/public/urdf/openarm_v10/regenerate.sh
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
XACRO_BIN="/opt/ros/jazzy/bin/xacro"
XACRO_SRC="$REPO_ROOT/controller/eduping-controller/src/openarm_description/urdf/robot/v10.urdf.xacro"
OUT="$REPO_ROOT/service/web-service/robot-web/public/urdf/openarm_v10/openarm.urdf"

if [[ ! -x "$XACRO_BIN" ]]; then
  echo "xacro not found at $XACRO_BIN — install ros-jazzy-xacro" >&2
  exit 1
fi
if [[ ! -f "$XACRO_SRC" ]]; then
  echo "xacro source missing: $XACRO_SRC — submodule not initialized?" >&2
  exit 1
fi

set +u
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
# shellcheck disable=SC1091
source "$REPO_ROOT/controller/eduping-controller/install/setup.bash"
set -u

"$XACRO_BIN" "$XACRO_SRC" \
  arm_type:=v10 \
  bimanual:=true \
  use_fake_hardware:=true \
  d435_mount_xyz:="0.05 0.0 0.62" \
  > "$OUT"

echo "regenerated $OUT ($(wc -l < "$OUT") lines)"
echo "  d435_mount: $(grep -A 1 d435_mount_joint "$OUT" | tail -1 | tr -s ' ')"
