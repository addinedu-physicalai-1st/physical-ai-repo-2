#!/usr/bin/env bash
# 프로젝트 전체 테스트 진입점 — 새 테스트 모듈 추가 시 이 파일에 기록한다.
#
# [server/ai] LLM 통합 테스트 — Ollama 서버가 로컬에서 실행 중이어야 합니다.
# 사용법:
#   bash scripts/test.sh               # 전체
#   bash scripts/test.sh -k gogoping   # 특정 케이스만
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AI_DIR="$REPO_ROOT/server/ai"

if ! curl -sf http://localhost:11434/api/tags > /dev/null; then
  echo "오류: Ollama 서버가 실행 중이지 않습니다 (http://localhost:11434)."
  exit 1
fi

echo "Ollama OK. 테스트 시작..."
conda run -n jazzy pytest "$AI_DIR/tests/" -v "$@" || true

echo
echo "[server/control] FastAPI + DB 테스트"
if pg_isready -h localhost -p 5432 -U pingder &>/dev/null; then
  cd "$REPO_ROOT"
  conda run -n jazzy pytest server/control/tests/ -v
else
  echo "  postgres 안 떠있음 — 'scripts/run_server.sh' 실행 후 다시 시도하세요. (skip)"
fi

echo
echo "[tests] Teleop (admin-ui ↔ control-server) 단위 테스트"
cd "$REPO_ROOT"
TELEOP_RC=0
conda run -n jazzy pytest \
  tests/test_teleop_router.py \
  tests/test_teleop_card.py \
  tests/test_ros_bridge_threadsafe.py \
  tests/test_teleop_arch_guards.py \
  -v "$@" || TELEOP_RC=$?
if [[ $TELEOP_RC -eq 0 ]]; then
  echo "[tests] Teleop 섹션 PASS"
else
  echo "[tests] Teleop 섹션 FAIL (exit=$TELEOP_RC)"
  exit $TELEOP_RC
fi

echo
echo "[ui/portal-ui] Vitest 단위 테스트"
PORTAL_DIR="$REPO_ROOT/ui/portal-ui"
if [[ -d "$PORTAL_DIR/node_modules" ]]; then
  cd "$PORTAL_DIR"
  npm run test -- --run
else
  echo "  node_modules 없음 — scripts/ui-portal.sh 한 번 실행 후 다시 시도하세요."
fi
