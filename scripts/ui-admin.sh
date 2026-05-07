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
APP_DIR="$REPO_ROOT/ui/admin-ui"
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

echo "[ui-admin] launching admin UI ($ENV_DESC, $PY)"
cd "$APP_DIR"
exec "$PY" main.py
