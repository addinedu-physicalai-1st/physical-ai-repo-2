#!/usr/bin/env bash
# scripts/db-seed.sh — alembic upgrade head + seed 데이터 INSERT (인터랙티브 메뉴)
#
# 활성 환경 감지: VIRTUAL_ENV (venv) → CONDA_ENV → CONDA_DEFAULT_ENV(base 제외)
# DB 위치는 시작 시점에 인터랙티브로 선택 — 로컬 docker 또는 원격 backend(jungbuntu).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
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

# DB 위치 선택 — 로컬 또는 원격. alembic / seed 가 읽는 settings.database_url 은
# DATABASE_URL 환경변수로 override 되므로, 여기서 export 해두면 두 경로 모두 작동.
echo ""
echo "  DB 위치를 선택하세요"
echo "  1) 로컬     (이 박스의 docker postgres @ localhost:5432)"
echo "  2) 원격     (machine_ips.json 의 'jungbuntu' IP @ :5432)"
echo ""
read -rp "  번호 입력 [1/2]: " DB_LOCATION

case "$DB_LOCATION" in
  1)
    DB_HOST="localhost"
    ;;
  2)
    # shellcheck source=/dev/null
    source "$SCRIPT_DIR/_run_lib.sh"
    DB_HOST="$(_runlib::lookup_machine_ip jungbuntu)"
    echo "[db-seed] backend 'jungbuntu' → $DB_HOST"
    ;;
  *)
    echo "[db-seed] 잘못된 입력입니다. 1 또는 2를 입력하세요." >&2
    exit 1
    ;;
esac

DB_PORT="5432"
export DATABASE_URL="postgresql+asyncpg://pingder:pingder@${DB_HOST}:${DB_PORT}/pingdergarten"
echo "[db-seed] DATABASE_URL=$DATABASE_URL"

# postgres 도달 확인 — bash 내장 /dev/tcp 로 TCP 단에서만 체크 (docker / pg_isready 의존 없음).
if ! timeout 2 bash -c "</dev/tcp/$DB_HOST/$DB_PORT" 2>/dev/null; then
  echo "[db-seed] postgres ($DB_HOST:$DB_PORT) 에 닿지 않습니다." >&2
  echo "[db-seed]   로컬: 'scripts/run_db_ai.sh' 또는 'scripts/run_server.sh' 로 postgres 기동" >&2
  echo "[db-seed]   원격: backend 박스에서 'scripts/run_db_ai.sh' 가 떠있는지 + 방화벽 / IP 확인" >&2
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
    run_in_env alembic -c db/control-db/control_db/alembic.ini downgrade base
    ;;
  *)
    echo "[db-seed] 잘못된 입력입니다. 1 또는 2를 입력하세요." >&2
    exit 1
    ;;
esac

echo "[db-seed] alembic upgrade head ($ENV_DESC)"
run_in_env alembic -c db/control-db/control_db/alembic.ini upgrade head

echo "[db-seed] seed 데이터 INSERT"
run_in_env python -m control_db.seed

echo "[db-seed] 완료"
