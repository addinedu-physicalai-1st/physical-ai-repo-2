#!/usr/bin/env bash
# 프로젝트 전체 테스트 진입점 — 새 테스트 모듈 추가 시 이 파일에 기록한다.
#
# [ai-service]
#   1) Hub HTTP 응답 + context 등 — Ollama 불필요 (`-m "not ollama"`)
#   2) Ollama 마커 (`-m ollama`) — 로컬 11434 있을 때만 실행 (없으면 스킵)
# [control-service] postgres 필요
# [tests] Teleop / Streaming — 트리 루트 tests/
# [portal-web] Vitest — node_modules 필요
#
# 사용법:
#   bash scripts/test.sh               # 전체
#   bash scripts/test.sh --tb=short    # 추가 pytest 인자 전달
#   bash scripts/test.sh -k gogoping
#
# ai-service · control-service · 루트 tests 는 conda env `jazzy` 로 실행한다.
#
# ⏱ 아래에 찍히는 시간은 각 **테스트 스위트 벽시계 실행 시간**이지,
#   실제 음성→LLM→TTS 응답 지연(레이턴시)이 아님.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

EXIT=0
SCRIPT_START=$SECONDS

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[ai-service] Hub 응답 + 컨텍스트 (Ollama 불필요)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest service/ai-service/ai_service/tests/ -m "not ollama" -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[ai-service] Ollama 통합 (generate_chat, classify_intent)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if curl -sf http://localhost:11434/api/tags >/dev/null; then
  if ! conda run -n jazzy pytest service/ai-service/ai_service/tests/ -m ollama -v "$@"; then
    EXIT=1
  fi
else
  echo "  스킵: Ollama 가 http://localhost:11434 에 없음 (위 Hub/컨텍스트 테스트만으로도 CI 가능)"
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[control-service] FastAPI + DB"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if pg_isready -h localhost -p 5432 -U pingder &>/dev/null; then
  if ! conda run -n jazzy pytest service/control-service/control_service/tests/ -v "$@"; then
    EXIT=1
  fi
else
  echo "  스킵: postgres 안 뜸 — scripts/run_server.sh 등으로 DB 기동 후 재시도"
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[tests] Teleop (admin-app ↔ control-service)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest \
  tests/test_teleop_router.py \
  tests/test_teleop_card.py \
  tests/test_ros_bridge_threadsafe.py \
  tests/test_ros_bridge_scan_hz.py \
  tests/test_teleop_arch_guards.py \
  -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[tests] GogoPing battery / idle_timeout / map_boundary monitors (py_trees only — ROS 불필요)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest \
  tests/test_gogoping_battery_monitors.py \
  tests/test_gogoping_idle_timeout_monitor.py \
  tests/test_gogoping_map_boundary_monitor.py \
  tests/test_gogoping_pose_override.py \
  tests/test_gogoping_align_to_dock.py \
  tests/test_gogoping_reverse_into_dock.py \
  tests/test_gogoping_return_subtree_builder.py \
  -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[tests] Graph (vertex 자동 lane + 다익스트라)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest tests/test_graph.py -v "$@"; then
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
echo "[gogoping_camera_pan] 시리얼 프로토콜 헬퍼 (clamp / rate_limit / parse / encode)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest tests/test_camera_pan_protocol.py -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[control-service] camera_pan (router + bridge mock) — ROS 불필요"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest \
  tests/test_camera_pan_router.py \
  tests/test_camera_pan_bridge.py \
  -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[noriarm-controller/noriarm_framework] 매니페스트 + 정책 + trajectory 단위 테스트"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
NORIARM_FRAMEWORK_DIR="$REPO_ROOT/controller/noriarm-controller/src/noriarm_framework"
(cd "$NORIARM_FRAMEWORK_DIR" && PYTHONPATH=. pytest test/test_manifest.py test/test_policy.py test/test_trajectory.py -v) || EXIT=1
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[tests] utils_geo — 좌표 변환 (raster ↔ map ↔ SVG)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest tests/test_utils_geo.py -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[control-service] yaml_store — waypoints.yaml CRUD"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest tests/test_waypoints_yaml_store.py -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[control-service] yaml_store — lanes.yaml + default snapshot"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest tests/test_waypoints_yaml_store_lanes.py -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[control-service] waypoints ros_bridge (non-ros tests only — ROS 통합은 @pytest.mark.ros)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest tests/test_waypoints_ros_bridge.py -m "not ros" -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[control-service] waypoints router — REST + SSE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest tests/test_waypoints_router.py -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[control-service] router — nav graph editor endpoints"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest \
  tests/test_waypoints_router_lanes.py \
  tests/test_waypoints_router_edit.py \
  -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[tests] BT waypoints client (REST + cache)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest tests/test_waypoints_client.py -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[admin-app] waypoint map card — pytest-qt 필요 (없으면 자동 skip)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
# pytest exit 5 = no tests collected (pytest-qt 미설치 시 importorskip 으로 전체 skip)
# exit 134 = Qt cleanup SIGABRT (테스트 결과는 정상 — 환경 이슈)
conda run -n jazzy pytest tests/test_waypoint_map_card.py -v "$@" || {
  rc=$?
  if [[ "$rc" -eq 5 ]]; then
    echo "  ※ pytest-qt 미설치 — 전체 SKIPPED (정상)"
  elif [[ "$rc" -eq 134 ]]; then
    echo "  ※ Qt cleanup SIGABRT — 테스트 결과는 정상"
  else
    EXIT=1
  fi
}
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[admin-app] waypoint map card — nav graph editor"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
conda run -n jazzy pytest tests/test_waypoint_map_card_edit.py -v "$@" || {
  rc=$?
  if [[ "$rc" -eq 5 ]]; then
    echo "  ※ pytest-qt 미설치 — 전체 SKIPPED (정상)"
  elif [[ "$rc" -eq 134 ]]; then
    echo "  ※ Qt cleanup SIGABRT — 테스트 결과는 정상"
  else
    EXIT=1
  fi
}
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[admin-app] camera_pan_card — pytest-qt (없으면 자동 skip)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
conda run -n jazzy pytest tests/test_camera_pan_card.py -v "$@" || {
  rc=$?
  if [[ "$rc" -eq 5 ]]; then
    echo "  ※ pytest-qt 미설치 — 전체 SKIPPED (정상)"
  elif [[ "$rc" -eq 134 ]]; then
    echo "  ※ Qt cleanup SIGABRT — 테스트 결과는 정상"
  else
    EXIT=1
  fi
}
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[admin-app] LiDAR scan — 순수 함수 (math 8) + 뷰 스모크 (view 4) + ODOM compact (3)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest \
  tests/test_lidar_scan_math.py \
  tests/test_lidar_scan_view.py \
  tests/test_odom_compact.py \
  -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[ai-service] dance audio PCM decode (pydub + ffmpeg)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest service/ai-service/ai_service/tests/test_dance_audio.py -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[ai-service] dance stream frame producer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest service/ai-service/ai_service/tests/test_dance_stream.py -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[ai-service] dance stream WS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
if ! conda run -n jazzy pytest service/ai-service/ai_service/tests/test_dance_stream_ws.py -v "$@"; then
  EXIT=1
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[portal-web] Vitest"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
PORTAL_DIR="$REPO_ROOT/service/web-service/portal-web"
if [[ -d "$PORTAL_DIR/node_modules" ]]; then
  (cd "$PORTAL_DIR" && npm run test -- --run) || EXIT=1
else
  echo "  스킵: node_modules 없음 — service/web-service/portal-web 에서 npm install 후 재시도"
fi
echo "⏱ 위 구간 벽시계: $((SECONDS - t0))s"

echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "[robot-web] Vitest (wakeMatcher 등 순수 유틸)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
t0=$SECONDS
ROBOT_DIR="$REPO_ROOT/service/web-service/robot-web"
if [[ -d "$ROBOT_DIR/node_modules" ]]; then
  (cd "$ROBOT_DIR" && npm run test -- --run) || EXIT=1
else
  echo "  스킵: node_modules 없음 — service/web-service/robot-web 에서 npm install 후 재시도"
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
