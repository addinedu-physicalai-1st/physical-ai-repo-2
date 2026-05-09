#!/usr/bin/env bash
# device/gogoping_stream_ws/scripts/run_camera_v4l2.sh
#
# 명시적 v4l2 backend alias — `CAMERA_BACKEND=v4l2 run_camera.sh` 와 동등.
# (run_camera.sh 의 default 가 이미 v4l2 라 동일 효과)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec env CAMERA_BACKEND=v4l2 "$SCRIPT_DIR/run_camera.sh" "$@"
