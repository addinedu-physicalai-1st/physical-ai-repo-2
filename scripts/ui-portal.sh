#!/usr/bin/env bash
# scripts/ui-portal.sh — Portal UI dev server 실행
# 사용법:
#   scripts/ui-portal.sh              # Control Service 가 8000 에 떠 있어야 함
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$REPO_ROOT/service/web-service/portal-web"

if [[ ! -d "$APP_DIR/node_modules" ]]; then
  echo "[ui-portal] node_modules 없음 — npm install 실행"
  (cd "$APP_DIR" && npm install)
fi

echo "[ui-portal] dev server (http://localhost:5174/)"
cd "$APP_DIR"
exec npm run dev -- --host
