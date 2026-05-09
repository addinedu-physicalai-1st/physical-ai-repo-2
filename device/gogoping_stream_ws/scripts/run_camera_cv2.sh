#!/usr/bin/env bash
# device/gogoping_stream_ws/scripts/run_camera_cv2.sh
#
# cv2 (opencv) backend alias — `CAMERA_BACKEND=cv2 run_camera.sh` 와 동등.
# linuxpy 미설치 환경 / 비-Linux / v4l2 호환 안 되는 카메라 fallback.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec env CAMERA_BACKEND=cv2 "$SCRIPT_DIR/run_camera.sh" "$@"
