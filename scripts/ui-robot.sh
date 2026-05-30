#!/usr/bin/env bash
# scripts/ui-robot.sh — Robot UI dev server 실행
#
# 사용:
#   scripts/ui-robot.sh eduping                 # control 서버 대화형 선택 (TTY 면 메뉴)
#   scripts/ui-robot.sh eduping hajuntu        # control = 등록된 머신(의사 머신) IP
#   scripts/ui-robot.sh eduping 192.168.0.152   # control = 직접 IP/호스트
#   scripts/ui-robot.sh eduping local           # control = localhost (이 머신)
#   CONTROL=hajuntu scripts/ui-robot.sh eduping
#   scripts/ui-robot.sh gogoping
#   scripts/ui-robot.sh noriarm
#
# VITE_ROBOT env 분기로 같은 코드베이스의 인스턴스를 띄운다.
# 첫 화면의 "탭해서 시작" 오버레이를 한 번 누르면 STT/TTS 가 활성화된다.
#
# control 서버 선택 (2-머신 배포):
#   robot-web 의 vite proxy 가 CONTROL_URL(:8000) / STREAMING_URL(:8100) 으로 /api·/ws 를
#   forward. eduping 머신에서 의사 머신(hajuntu)의 control 서버를 쓰려면 그 IP 를 골라야 함.
#   2번째 인자 또는 CONTROL env 로 지정 — 머신이름(shared/machine_ips.json) | IP | local.
#   미지정 + TTY 면 메뉴, 비대화형이면 localhost (기존 동작 유지).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/_run_lib.sh"

ROBOT="${1:-}"
CONTROL_ARG="${2:-}"
case "$ROBOT" in
  eduping|gogoping|noriarm) ;;
  "")
    echo "usage: $0 <eduping|gogoping|noriarm> [control: 머신이름|IP|local]" >&2
    exit 2
    ;;
  *)
    echo "unknown robot: $ROBOT (eduping|gogoping|noriarm 중 하나)" >&2
    exit 2
    ;;
esac

CONTROL_PORT="${CONTROL_PORT:-8000}"
STREAMING_PORT="${STREAMING_PORT:-8100}"
MACHINE_JSON="$REPO_ROOT/shared/machine_ips.json"

# control host 결정: 인자/env 우선 → 없으면 (TTY 메뉴 | 비대화형 localhost).
# 해석/메뉴 로직은 _run_lib.sh 의 공용 헬퍼 (device-eduping.sh 와 공유).
control_sel="${CONTROL_ARG:-${CONTROL:-}}"
if [[ -n "$control_sel" ]]; then
  CONTROL_HOST="$(_runlib::resolve_control_token "$control_sel" "$MACHINE_JSON")" || {
    echo "[ui-robot] control 서버 '$control_sel' 해석 실패 — 중단" >&2
    exit 1
  }
elif [[ -t 0 ]]; then
  CONTROL_HOST="$(_runlib::choose_control_host "Control 서버 ($ROBOT UI vite proxy :$CONTROL_PORT/:$STREAMING_PORT)" "$MACHINE_JSON")"
else
  CONTROL_HOST="localhost"
fi

CONTROL_URL="http://$CONTROL_HOST:$CONTROL_PORT"
STREAMING_URL="http://$CONTROL_HOST:$STREAMING_PORT"

APP_DIR="$REPO_ROOT/service/web-service/robot-web"

if [[ ! -d "$APP_DIR/node_modules" ]]; then
  echo "[ui-robot] node_modules 없음 — npm install 실행"
  (cd "$APP_DIR" && npm install)
fi

if [[ "$ROBOT" == "noriarm" ]]; then
  echo "[ui-robot] NoriArm 모델 점검 (블럭쌓기 ACT)"
  if ! python "$REPO_ROOT/scripts/noriarm_check_models.py"; then
    echo "[ui-robot] 모델 점검 실패 — 인터넷 연결 확인 후 다시 시도하세요" >&2
    exit 1
  fi
fi

echo "[ui-robot] $ROBOT 인스턴스 시작 (http://localhost:5173/)"
echo "[ui-robot] control 서버 → $CONTROL_URL  (streaming $STREAMING_URL)"
cd "$APP_DIR"
VITE_ROBOT="$ROBOT" CONTROL_URL="$CONTROL_URL" STREAMING_URL="$STREAMING_URL" \
  exec npm run dev -- --host
