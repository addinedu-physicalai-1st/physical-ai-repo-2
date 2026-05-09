#!/usr/bin/env bash
# device/gogoping_stream_ws/scripts/run_camera.sh
#
# Vic Pinky / EduPing / NoriArm 노트북에서 카메라 UDP 송출 스크립트 wrapper.
#
# 동작 (PLAN §1.5):
#   - 기본 default ON: 실행 직후 Control Server 로 영상 송출 시작
#   - admin 의 수동 STOP 신호 수신 시에만 일시 중지 (자동 트리거 없음)
#   - 이번 SR 은 수동 실행. 부팅 자동 시작 (systemd) 은 별도 SR.
#
# Backend 선택 (CAMERA_BACKEND):
#   v4l2  default — linuxpy 로 카메라 native MJPEG 직접 송출 (저지연, 권장)
#   cv2   fallback — opencv 로 캡처+JPEG 재인코딩 (linuxpy 미설치 환경)
#
# 환경변수 (또는 .env):
#   CAMERA_BACKEND       v4l2 (default) | cv2
#   CAMERA_ROBOT         gogoping | eduping | noriarm — 필수
#   CONTROL_SERVER_NAME  shared/machine_ips.json 의 hostname key — 기본 'tonyno' (예: tonyno, leekt)
#   CAMERA_SERVER_IP     Control Server IP 직접 지정 시 — 미지정 시 CONTROL_SERVER_NAME 으로 자동 lookup
#   CAMERA_DEVICE        V4L2 디바이스 — 기본 /dev/video0
#   CAMERA_WIDTH         기본 640
#   CAMERA_HEIGHT        기본 480
#   CAMERA_FPS           기본 25
#   CAMERA_QUALITY       MJPEG q (1..100) — 기본 60 (cv2 모드만 적용. v4l2 는 카메라 native quality)
#   CAMERA_STREAM_ID     0..6 — 기본 0 (primary)
#   CAMERA_LOG_LEVEL     DEBUG | INFO | WARNING | ERROR — 기본 INFO
#
# 사용:
#   CAMERA_ROBOT=gogoping ./run_camera.sh                       # default v4l2
#   CAMERA_ROBOT=gogoping CAMERA_BACKEND=cv2 ./run_camera.sh    # cv2 fallback
#   CAMERA_ROBOT=gogoping ./run_camera_v4l2.sh                  # 명시적 v4l2 (alias)
#   CAMERA_ROBOT=gogoping ./run_camera_cv2.sh                   # 명시적 cv2 (alias)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$WS_ROOT/../.." && pwd)"

# .env 자동 로드 (우선순위: WS_ROOT/.env > REPO_ROOT/.env)
if [[ -f "$WS_ROOT/.env" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$WS_ROOT/.env"; set +a
elif [[ -f "$REPO_ROOT/.env" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$REPO_ROOT/.env"; set +a
fi

: "${CAMERA_ROBOT:?CAMERA_ROBOT 환경변수가 필요합니다 (gogoping|eduping|noriarm)}"

CAMERA_BACKEND="${CAMERA_BACKEND:-v4l2}"
CAMERA_DEVICE="${CAMERA_DEVICE:-/dev/video0}"
CAMERA_WIDTH="${CAMERA_WIDTH:-640}"
CAMERA_HEIGHT="${CAMERA_HEIGHT:-480}"
CAMERA_FPS="${CAMERA_FPS:-25}"
CAMERA_QUALITY="${CAMERA_QUALITY:-60}"
CAMERA_STREAM_ID="${CAMERA_STREAM_ID:-0}"
CAMERA_LOG_LEVEL="${CAMERA_LOG_LEVEL:-INFO}"

# Backend → 실행할 Python 스크립트
case "$CAMERA_BACKEND" in
  v4l2)
    STREAMER_SCRIPT="camera_streamer_v4l2.py"
    BACKEND_DESC="v4l2 (저지연, linuxpy)"
    ;;
  cv2)
    STREAMER_SCRIPT="camera_streamer.py"
    BACKEND_DESC="cv2 (opencv fallback)"
    ;;
  *)
    echo "[run_camera] 잘못된 CAMERA_BACKEND='$CAMERA_BACKEND' (v4l2|cv2)" >&2
    exit 1
    ;;
esac

# 활성 환경 감지: VIRTUAL_ENV → CONDA_DEFAULT_ENV (base 제외)
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  PY="$VIRTUAL_ENV/bin/python"
elif [[ -n "${CONDA_DEFAULT_ENV:-}" && "${CONDA_DEFAULT_ENV}" != "base" ]]; then
  PY="conda run --no-capture-output -n $CONDA_DEFAULT_ENV python"
else
  echo "[run_camera] 활성화된 venv/conda 환경이 없습니다." >&2
  echo "             'conda activate <env>' 또는 venv 활성화 후 실행하세요." >&2
  exit 1
fi

# CAMERA_SERVER_IP 가 미지정이면 stub — Python 측이 machine_ips.json 자동 lookup
EXTRA_ARGS=()
if [[ -n "${CAMERA_SERVER_IP:-}" ]]; then
  EXTRA_ARGS+=(--server-ip "$CAMERA_SERVER_IP")
fi

echo "[run_camera] backend=$BACKEND_DESC"
echo "[run_camera] robot=$CAMERA_ROBOT device=$CAMERA_DEVICE"
echo "[run_camera] ${CAMERA_WIDTH}x${CAMERA_HEIGHT}@${CAMERA_FPS} q=${CAMERA_QUALITY} stream=${CAMERA_STREAM_ID}"
if [[ -n "${CAMERA_SERVER_IP:-}" ]]; then
  echo "[run_camera] server=$CAMERA_SERVER_IP (env CAMERA_SERVER_IP override)"
else
  CONTROL_HOST="${CONTROL_SERVER_NAME:-tonyno}"
  echo "[run_camera] server=auto-lookup from shared/machine_ips.json (key '$CONTROL_HOST')"
fi

exec $PY "$SCRIPT_DIR/$STREAMER_SCRIPT" \
  --robot         "$CAMERA_ROBOT" \
  --camera-device "$CAMERA_DEVICE" \
  --width         "$CAMERA_WIDTH" \
  --height        "$CAMERA_HEIGHT" \
  --fps           "$CAMERA_FPS" \
  --jpeg-quality  "$CAMERA_QUALITY" \
  --stream-id     "$CAMERA_STREAM_ID" \
  --log-level     "$CAMERA_LOG_LEVEL" \
  "${EXTRA_ARGS[@]}"
