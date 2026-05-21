#!/usr/bin/env bash
# scripts/ui-admin.sh — PyQt5 admin UI 실행
# 사용법:
#   scripts/ui-admin.sh                 # 활성 환경 자동 탐지
#   CONDA_ENV=pdg scripts/ui-admin.sh   # conda env 이름 명시
#
# 탐색 순서:
#   1) VIRTUAL_ENV (venv 활성)
#   2) CONDA_ENV 환경 변수
#   3) 활성화된 conda env (CONDA_DEFAULT_ENV, base 제외)
#   4) miniforge3/miniconda3/anaconda3 의 envs 중 PyQt5 가 설치된 첫 env
#
# macOS 에서 `conda run` 으로 PyQt5 GUI 를 띄우면 Cocoa 이벤트 루프가
# stdio 리디렉션과 충돌해 Bus error 가 난다. 환경의 python 바이너리를 직접 호출한다.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$REPO_ROOT/app/admin-app"
CONDA_BASES=("$HOME/miniforge3" "$HOME/miniconda3" "$HOME/anaconda3" "/opt/homebrew/Caskroom/miniforge/base")

# 주어진 conda env 이름의 python 경로 반환 (없으면 빈 문자열)
find_python_for_env() {
  local name="$1"
  for base in "${CONDA_BASES[@]}"; do
    local candidate="$base/envs/$name/bin/python"
    if [[ -x "$candidate" ]]; then
      echo "$candidate"
      return
    fi
  done
}

ENV_DESC=""
PY=""

# 1) venv 활성
if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
  PY="$VIRTUAL_ENV/bin/python"
  ENV_DESC="venv:$VIRTUAL_ENV"
# 2) CONDA_ENV 명시
elif [[ -n "${CONDA_ENV:-}" ]]; then
  PY="$(find_python_for_env "$CONDA_ENV")"
  if [[ -z "$PY" ]]; then
    echo "[ui-admin] CONDA_ENV='$CONDA_ENV' 의 python 을 찾지 못했습니다." >&2
    exit 1
  fi
  ENV_DESC="conda:$CONDA_ENV"
# 3) 활성화된 conda env (base 제외)
elif [[ -n "${CONDA_DEFAULT_ENV:-}" && "${CONDA_DEFAULT_ENV}" != "base" ]]; then
  PY="$(find_python_for_env "$CONDA_DEFAULT_ENV")"
  [[ -n "$PY" ]] && ENV_DESC="conda:$CONDA_DEFAULT_ENV"
fi

# 4) PyQt5 가 설치된 conda env 자동 탐색
if [[ -z "$PY" ]]; then
  for base in "${CONDA_BASES[@]}"; do
    [[ -d "$base/envs" ]] || continue
    for env_dir in "$base/envs"/*; do
      candidate="$env_dir/bin/python"
      if [[ -x "$candidate" ]] && "$candidate" -c "from PyQt5 import QtCore" >/dev/null 2>&1; then
        PY="$candidate"
        ENV_DESC="conda:$(basename "$env_dir")"
        break 2
      fi
    done
  done
fi

if [[ -z "$PY" ]]; then
  echo "[ui-admin] 활성화된 환경이 없고 PyQt5 가 설치된 conda env 도 찾지 못했습니다." >&2
  echo "[ui-admin] 'conda activate <env>' 또는 venv 활성화 후 실행하세요." >&2
  exit 1
fi

if ! "$PY" -c "from PyQt5 import QtCore" >/dev/null 2>&1; then
  echo "[ui-admin] PyQt5 미설치 — '$ENV_DESC' 에 'pip install -e .' 실행"
  "$PY" -m pip install -e "$REPO_ROOT"
fi

if ! "$PY" -c "from PyQt5.QtWebEngineWidgets import QWebEngineView" >/dev/null 2>&1; then
  echo "[ui-admin] PyQtWebEngine 미설치 — EduPing 3D 뷰어·별창 비교에 필요"
  "$PY" -m pip install PyQtWebEngine
fi

# EduPing 탭의 3D 뷰어가 leader bringup 의 `/eduping/leader/joint_states` 를 직접
# 받기 위해 rclpy 가 필요. PY 의 site-packages 가 ROS 의 python path 를 못 찾는
# 경우가 흔해 (특히 conda env), 여기서 ROS env 와 workspace overlay 를 source 해
# PYTHONPATH·LD_LIBRARY_PATH 를 설정한다. ROS 미설치 환경에서는 조용히 패스 — 그
# 경우 admin-app 의 EduPing 탭에서 "rclpy 시작 실패" 안내가 뜬다.
ROS_SETUP_CANDIDATES=(
  "/opt/ros/jazzy/setup.bash"
  "/opt/ros/humble/setup.bash"
  "/opt/ros/iron/setup.bash"
)
# ROS setup.bash references several env vars (AMENT_TRACE_SETUP_FILES, COLCON_*,
# AMENT_CURRENT_PREFIX 등) that may be unset on a fresh shell. Our `set -u` would
# abort the whole script on first reference. Temporarily relax around source.
set +u
for cand in "${ROS_SETUP_CANDIDATES[@]}"; do
  if [[ -f "$cand" ]]; then
    # shellcheck disable=SC1090
    source "$cand"
    echo "[ui-admin] sourced ROS: $cand"
    break
  fi
done

# eduping controller workspace overlay (sensor_msgs 등은 ROS base 에서, 커스텀
# 메시지·노드는 워크스페이스에서). 빌드 안 됐으면 패스.
WS_SETUP="$REPO_ROOT/controller/eduping-controller/install/setup.bash"
if [[ -f "$WS_SETUP" ]]; then
  # shellcheck disable=SC1090
  source "$WS_SETUP"
  echo "[ui-admin] sourced workspace: $WS_SETUP"
fi
set -u

# Qt WebEngine → Chromium: prefer hardware WebGL (see app/admin-app/webengine_gpu.py).
# Override entirely: QTWEBENGINE_CHROMIUM_FLAGS="..."
if [[ -z "${QTWEBENGINE_CHROMIUM_FLAGS:-}" ]]; then
  export QTWEBENGINE_CHROMIUM_FLAGS="--enable-gpu --enable-webgl --ignore-gpu-blocklist --enable-accelerated-2d-canvas --disable-software-rasterizer --use-gl=desktop"
fi

echo "[ui-admin] launching admin UI ($ENV_DESC, $PY) ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-unset}"
echo "[ui-admin] QTWEBENGINE_CHROMIUM_FLAGS=${QTWEBENGINE_CHROMIUM_FLAGS}"
cd "$APP_DIR"
exec "$PY" main.py
