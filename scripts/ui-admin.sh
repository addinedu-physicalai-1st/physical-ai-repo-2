#!/usr/bin/env bash
# scripts/ui-admin.sh — PyQt5 admin UI 실행
# 사용법:
#   scripts/ui-admin.sh
#
# macOS 에서 `conda run` 으로 PyQt5 GUI 를 띄우면 Cocoa 이벤트 루프가
# stdio 리디렉션과 충돌해 Bus error 가 난다. 환경의 python 바이너리를 직접 호출한다.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$REPO_ROOT/ui/admin-ui"
ENV_NAME="jazzy"

# conda env python 경로 탐색 (miniforge3, miniconda3, anaconda3 모두 지원)
CONDA_PY=""
for base in "$HOME/miniforge3" "$HOME/miniconda3" "$HOME/anaconda3" "/opt/homebrew/Caskroom/miniforge/base"; do
  candidate="$base/envs/$ENV_NAME/bin/python"
  if [[ -x "$candidate" ]]; then
    CONDA_PY="$candidate"
    break
  fi
done

if [[ -z "$CONDA_PY" ]]; then
  echo "[ui-admin] '$ENV_NAME' 환경의 python 을 찾지 못했습니다. conda 설치 위치를 확인하세요." >&2
  exit 1
fi

if ! "$CONDA_PY" -c "from PyQt5 import QtCore" >/dev/null 2>&1; then
  echo "[ui-admin] PyQt5 미설치 — '$ENV_NAME' 환경에 설치"
  "$CONDA_PY" -m pip install -e "$REPO_ROOT"
fi

echo "[ui-admin] launching admin UI ($CONDA_PY)"
cd "$APP_DIR"
exec "$CONDA_PY" main.py
