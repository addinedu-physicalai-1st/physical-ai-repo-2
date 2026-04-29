#!/usr/bin/env bash
# scripts/db-seed.sh — alembic upgrade head + seed 데이터 INSERT (인터랙티브 메뉴)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# postgres 떠있는지 확인
if ! pg_isready -h localhost -p 5432 -U pingder &>/dev/null; then
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
    echo "[db-seed] alembic downgrade base"
    conda run -n jazzy alembic -c server/db/alembic.ini downgrade base
    ;;
  *)
    echo "[db-seed] 잘못된 입력입니다. 1 또는 2를 입력하세요." >&2
    exit 1
    ;;
esac

echo "[db-seed] alembic upgrade head"
conda run -n jazzy alembic -c server/db/alembic.ini upgrade head

echo "[db-seed] seed 데이터 INSERT"
conda run -n jazzy python -m server.db.seed

echo "[db-seed] 완료"
