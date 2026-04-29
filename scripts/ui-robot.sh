#!/usr/bin/env bash
# scripts/ui-robot.sh — Robot UI dev server 실행
#
# 사용:
#   scripts/ui-robot.sh eduping
#   scripts/ui-robot.sh gogoping
#   scripts/ui-robot.sh noriarm
#
# VITE_ROBOT env 분기로 같은 코드베이스의 인스턴스를 띄운다.
# 첫 화면의 "탭해서 시작" 오버레이를 한 번 누르면 STT/TTS 가 활성화된다.
set -euo pipefail

ROBOT="${1:-}"
case "$ROBOT" in
  eduping|gogoping|noriarm) ;;
  "")
    echo "usage: $0 <eduping|gogoping|noriarm>" >&2
    exit 2
    ;;
  *)
    echo "unknown robot: $ROBOT (eduping|gogoping|noriarm 중 하나)" >&2
    exit 2
    ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$REPO_ROOT/ui/robot-ui"

if [[ ! -d "$APP_DIR/node_modules" ]]; then
  echo "[ui-robot] node_modules 없음 — npm install 실행"
  (cd "$APP_DIR" && npm install)
fi

echo "[ui-robot] $ROBOT 인스턴스 시작 (http://localhost:5173/)"
cd "$APP_DIR"
VITE_ROBOT="$ROBOT" exec npm run dev -- --host
