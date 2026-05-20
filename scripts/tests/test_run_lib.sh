#!/usr/bin/env bash
# _run_lib.sh 의 핵심 함수 단순 smoke test.
# 외부 의존(jq, lsof)이 없는 검증만 — 환경에 따라 false negative 를 내는 검사는 피함.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$SCRIPT_DIR/../_run_lib.sh"

if [[ ! -f "$LIB" ]]; then
  echo "FAIL: $LIB 없음" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$LIB"

# --- 1. wrap_cmd: VIRTUAL_ENV 케이스 ---
(
  export VIRTUAL_ENV="/tmp/fakevenv"
  unset CONDA_DEFAULT_ENV
  _runlib::detect_env
  out="$(_runlib::wrap_cmd python -m foo)"
  expected="/tmp/fakevenv/bin/python -m foo"
  if [[ "$out" != "$expected" ]]; then
    echo "FAIL: venv wrap_cmd — got '$out', want '$expected'" >&2
    exit 1
  fi
)

# --- 2. wrap_cmd: CONDA_DEFAULT_ENV 케이스 ---
(
  unset VIRTUAL_ENV
  export CONDA_DEFAULT_ENV="jazzy"
  _runlib::detect_env
  out="$(_runlib::wrap_cmd uvicorn app:app)"
  expected="conda run --no-capture-output -n jazzy uvicorn app:app"
  if [[ "$out" != "$expected" ]]; then
    echo "FAIL: conda wrap_cmd — got '$out', want '$expected'" >&2
    exit 1
  fi
)

# --- 3. lookup_machine_ip: 정상 ---
tmp_json="$(mktemp)"
cat > "$tmp_json" <<'JSON'
{
  "jungbuntu": {"mac": "e8:65:38:23:fd:6f", "ip": "192.168.0.142", "found_at": "2026-05-20T10:00:00+09:00"},
  "vic": {"mac": "2c:cf:67:e7:ee:29", "ip": null, "found_at": "2026-05-20T10:00:00+09:00"}
}
JSON

ip="$(_runlib::lookup_machine_ip jungbuntu "$tmp_json")"
if [[ "$ip" != "192.168.0.142" ]]; then
  echo "FAIL: lookup_machine_ip jungbuntu — got '$ip', want '192.168.0.142'" >&2
  exit 1
fi

# --- 4. lookup_machine_ip: ip=null 이면 비-zero exit ---
if _runlib::lookup_machine_ip vic "$tmp_json" >/dev/null 2>&1; then
  echo "FAIL: lookup_machine_ip vic (ip=null) — exit 0 인데 비-zero 기대" >&2
  exit 1
fi

# --- 5. lookup_machine_ip: 없는 키면 비-zero exit ---
if _runlib::lookup_machine_ip nosuchname "$tmp_json" >/dev/null 2>&1; then
  echo "FAIL: lookup_machine_ip nosuchname — exit 0 인데 비-zero 기대" >&2
  exit 1
fi

rm -f "$tmp_json"
echo "PASS: _run_lib.sh smoke tests"
