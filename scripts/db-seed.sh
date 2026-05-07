#!/usr/bin/env bash
# scripts/db-seed.sh — alembic upgrade head + seed 데이터 INSERT (인터랙티브 메뉴)
#
# 활성 환경 감지: VIRTUAL_ENV (venv) → CONDA_ENV → CONDA_DEFAULT_ENV(base 제외)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# 활성 환경에서 실행하는 헬퍼
ENV_DESC=""
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  ENV_DESC="venv:$VIRTUAL_ENV"
  run_in_env() { "$VIRTUAL_ENV/bin/$1" "${@:2}"; }
else
  ENV_NAME="${CONDA_ENV:-}"
  if [[ -z "$ENV_NAME" && -n "${CONDA_DEFAULT_ENV:-}" && "${CONDA_DEFAULT_ENV}" != "base" ]]; then
    ENV_NAME="$CONDA_DEFAULT_ENV"
  fi
  if [[ -z "$ENV_NAME" ]]; then
    echo "[db-seed] 활성화된 conda/venv 환경이 없습니다. 'conda activate <env>' 또는 venv 활성화 후 실행하세요." >&2
    exit 1
  fi
  ENV_DESC="conda:$ENV_NAME"
  run_in_env() { conda run --no-capture-output -n "$ENV_NAME" "$@"; }
fi

# postgres 떠있는지 확인 (docker compose health status 체크)
if ! docker compose ps postgres --format json 2>/dev/null | grep -q '"Health":"healthy"'; then
  echo "[db-seed] postgres 가 떠있지 않습니다. 먼저 'scripts/run_server.sh' 실행" >&2
  exit 1
fi

echo ""
echo "  DB seed 모드를 선택하세요"
echo "  1) 기존 데이터 유지하며 추가 (idempotent)"
echo "  2) 전체 초기화 후 새로 seed  (⚠ 데이터 전체 삭제)"
echo ""
read -rp "  번호 입력 [1/2]: " MODE

case "$MODE" in
  1)
    echo "[db-seed] 모드: 추가"
    ;;
  2)
    echo "[db-seed] 모드: 전체 초기화"
    echo "[db-seed] alembic downgrade base ($ENV_DESC)"
    run_in_env alembic -c server/db/alembic.ini downgrade base
    ;;
  *)
    echo "[db-seed] 잘못된 입력입니다. 1 또는 2를 입력하세요." >&2
    exit 1
    ;;
esac

echo "[db-seed] alembic upgrade head ($ENV_DESC)"
run_in_env alembic -c server/db/alembic.ini upgrade head

echo "[db-seed] seed 데이터 INSERT"
run_in_env python -m server.db.seed

echo "[db-seed] 완료"
