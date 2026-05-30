#!/usr/bin/env bash
# scripts/sync_openarm_assets.sh — populate the doctor-UI OpenArm meshes.
#
# Why this exists: portal-web's doctor teleop scene (src/doctor/teleop3d/ArmUrdf.ts)
# loads a static URDF served by vite at
#   /openarm/openarm_bimanual.urdf   (packages map: openarm_description -> /openarm)
# The URDF references `package://openarm_description/meshes/...`, so the meshes/ tree
# must sit at service/web-service/portal-web/public/openarm/meshes/. Without it every
# link renders invisible (URDFLoader fetches no geometry → empty scene).
#
# The meshes (~72MB of .dae/.stl) are gitignored (see .gitignore) and NOT committed,
# so a fresh checkout has none. Run this once before launching portal-web.
#
# Source of truth: the `openarm_description` submodule meshes (same files the ROS
# side uses). The URDF itself IS committed; if the upstream xacro changes, regenerate
# it the same way robot-web does (see robot-web/public/urdf/openarm_v10/regenerate.sh).
#
# Usage:
#   bash scripts/sync_openarm_assets.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/controller/eduping-controller/src/openarm_description/meshes"
DST="$REPO_ROOT/service/web-service/portal-web/public/openarm/meshes"

if [[ ! -d "$SRC" ]]; then
  echo "[sync_openarm_assets] mesh source missing: $SRC" >&2
  echo "  openarm_description submodule not initialized. Run:" >&2
  echo "  git submodule update --init controller/eduping-controller/src/openarm_description" >&2
  exit 1
fi

# Sanity: the URDF's visual meshes must all exist in the source tree.
URDF="$REPO_ROOT/service/web-service/portal-web/public/openarm/openarm_bimanual.urdf"
if [[ -f "$URDF" ]]; then
  missing=0
  while IFS= read -r rel; do
    [[ -f "$SRC/${rel#meshes/}" ]] || { echo "[sync_openarm_assets] ⚠ URDF refs missing mesh: $rel" >&2; missing=1; }
  done < <(grep -oE "meshes/[^\"']*\.dae" "$URDF" | sort -u)
  [[ "$missing" -eq 0 ]] || echo "[sync_openarm_assets] (continuing — submodule may be a different openarm version)" >&2
fi

rm -rf "$DST"
cp -r "$SRC" "$DST"
echo "[sync_openarm_assets] ✓ synced $(find "$DST" -type f | wc -l) mesh files → public/openarm/meshes/"
