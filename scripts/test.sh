#!/usr/bin/env bash
# 프로젝트 전체 테스트 진입점 — 새 테스트 모듈 추가 시 이 파일에 기록한다.
#
# [server/ai]
#   1) Hub HTTP 응답 + context 등 — Ollama 불필요 (`-m "not ollama"`)
#   2) Ollama 마커 (`-m ollama`) — 로컬 11434 있을 때만 실행 (없으면 스킵)
# [server/control] postgres 필요
# [tests] Teleop / Streaming — 트리 루트 tests/
# [ui/portal-ui] Vitest — node_modules 필요
#
# 사용법:
#   bash scripts/test.sh               # 전체
#   bash scripts/test.sh --tb=short    # 추가 pytest 인자 전달
#   bash scripts/test.sh -k gogoping
#
# server/ai·control·루트 tests 는 conda env `jazzy` 로 실행한다.
#
# ⏱ 아래에 찍히는 시간은 각 **테스트 스위트 벽시계 실행 시간**이지,
#   실제 음성→LLM→TTS 응답 지연(레이턴시)이 아님.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

EXIT=0
SCRIPT_START=$SECONDS

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[server/ai] Hub 응답 + 컨텍스트 (Ollama 불필요)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest server/ai/tests/ -m "not ollama" -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[server/ai] Ollama 통합 (generate_chat, classify_intent)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if curl -sf http://localhost:11434/api/tags >/dev/null; then
  if ! conda run -n jazzy pytest server/ai/tests/ -m ollama -v "$@"; then
    EXIT=1
  fi
else
  echo "  스킵: Ollama 가 http://localhost:11434 에 없음 (위 Hub/컨텍스트 테스트만으로도 CI 가능)"
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[server/control] FastAPI + DB"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if pg_isready -h localhost -p 5432 -U pingder &>/dev/null; then
  if ! conda run -n jazzy pytest server/control/tests/ -v "$@"; then
    EXIT=1
  fi
else
  echo "  스킵: postgres 안 뜸 — scripts/run_server.sh 등으로 DB 기동 후 재시도"
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[tests] Teleop (admin-ui ↔ control-server)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest \
  tests/test_teleop_router.py \
  tests/test_teleop_card.py \
  tests/test_ros_bridge_threadsafe.py \
  tests/test_teleop_arch_guards.py \
  -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[tests] Streaming (UDP camera → WS fan-out)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest \
  tests/test_streaming_protocol.py \
  tests/test_streaming_frame_hub.py \
  tests/test_streaming_frame_drop.py \
  tests/test_streaming_robot_controller.py \
  tests/test_streaming_ws_router.py \
  -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[ui/portal-ui] Vitest"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
PORTAL_DIR="$REPO_ROOT/ui/portal-ui"
if [[ -d "$PORTAL_DIR/node_modules" ]]; then
  (cd "$PORTAL_DIR" && npm run test -- --run) || EXIT=1
else
  echo "  스킵: node_modules 없음 — ui/portal-ui 에서 npm install 후 재시도"
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "⏱ scripts/test.sh 전체 벽시계: $((SECONDS - SCRIPT_START))s"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [[ "$EXIT" -eq 0 ]]; then
  echo "전체 테스트 스크립트 종료: 성공"
else
  echo "전체 테스트 스크립트 종료: 일부 실패 (위 로그 확인)"
fi
exit "$EXIT"
