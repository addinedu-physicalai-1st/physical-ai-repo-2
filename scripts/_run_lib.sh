#!/usr/bin/env bash
# 공용 helper — run_db_ai.sh / run_control.sh 가 source.
# run_server.sh 는 사용하지 않는다 (해당 스크립트는 손대지 않는 정책).
#
# 함수 이름은 `_runlib::` prefix — 호출 쪽 네임스페이스를 오염시키지 않기 위해.

# Bash 4+ 의 `declare -A` 가 필요한 함수가 있으므로 sanity check 만 — 별도 의존 없음.

# detect_env: 활성 Python 환경 감지. 전역 ENV_DESC 와 함수 _runlib::wrap_cmd 를 셋업.
# 호출 후 ENV_DESC 가 로그용 문자열로 채워진다.
_runlib::detect_env() {
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    ENV_DESC="venv:$VIRTUAL_ENV"
    _RUNLIB_MODE="venv"
    _RUNLIB_VENV_BIN="$VIRTUAL_ENV/bin"
    return 0
  fi

  local env_name="${CONDA_ENV:-}"
  if [[ -z "$env_name" && -n "${CONDA_DEFAULT_ENV:-}" && "${CONDA_DEFAULT_ENV}" != "base" ]]; then
    env_name="$CONDA_DEFAULT_ENV"
  fi
  if [[ -z "$env_name" ]]; then
    echo "[run_lib] 활성화된 conda/venv 환경이 없습니다. 'conda activate <env>' 또는 venv 활성화 후 실행." >&2
    exit 1
  fi
  ENV_DESC="conda:$env_name"
  _RUNLIB_MODE="conda"
  _RUNLIB_CONDA_NAME="$env_name"
}

# wrap_cmd <cmd> <args...>
# detect_env 가 감지한 환경에서 실행할 명령 문자열을 stdout 으로 echo.
_runlib::wrap_cmd() {
  if [[ "${_RUNLIB_MODE:-}" == "venv" ]]; then
    echo "$_RUNLIB_VENV_BIN/$*"
  elif [[ "${_RUNLIB_MODE:-}" == "conda" ]]; then
    echo "conda run --no-capture-output -n $_RUNLIB_CONDA_NAME $*"
  else
    echo "[run_lib] wrap_cmd: detect_env 가 먼저 호출돼야 합니다." >&2
    exit 1
  fi
}

# warn_port_in_use <port> [tcp|udp]
# 포트가 LISTEN 중이면 stderr 에 경고만 출력 (치명적이지 않음).
# lsof 가 없으면 silent skip.
_runlib::warn_port_in_use() {
  local port="$1"
  local proto="${2:-tcp}"
  command -v lsof >/dev/null 2>&1 || return 0
  if [[ "$proto" == "udp" ]]; then
    if lsof -i "UDP:$port" -P -sUDP:LISTEN &>/dev/null; then
      echo "[run_lib] ⚠ UDP $port 가 이미 사용 중 — 바인드 실패하면 window 에 에러가 표시됩니다." >&2
    fi
  else
    if lsof -i ":$port" -P -sTCP:LISTEN &>/dev/null; then
      echo "[run_lib] ⚠ 포트 $port 가 이미 사용 중 — 바인드 실패하면 window 에 에러가 표시됩니다." >&2
    fi
  fi
}

# lookup_machine_ip <name> [json_path]
# shared/machine_ips.json (또는 두번째 인자로 지정한 파일) 에서 <name>.ip 추출 → stdout.
# 파일 없음 / 키 없음 / ip=null 이면 stderr 안내 + return 1.
_runlib::lookup_machine_ip() {
  local name="$1"
  local json_path="${2:-}"
  if [[ -z "$json_path" ]]; then
    local repo_root
    repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    json_path="$repo_root/shared/machine_ips.json"
  fi

  if [[ ! -f "$json_path" ]]; then
    echo "[run_lib] $json_path 없음 — 먼저 'scripts/find_machine_ips.sh' 실행." >&2
    return 1
  fi
  if ! command -v jq >/dev/null 2>&1; then
    echo "[run_lib] jq 가 PATH 에 없습니다." >&2
    return 1
  fi

  local ip
  ip="$(jq -r --arg n "$name" '.[$n].ip // empty' "$json_path")"
  if [[ -z "$ip" || "$ip" == "null" ]]; then
    echo "[run_lib] '$name' 의 IP 를 $json_path 에서 못 찾음 — 'scripts/find_machine_ips.sh' 재실행." >&2
    return 1
  fi
  echo "$ip"
}

# resolve_control_token <token> [json_path] → host 를 stdout 으로.
# token: ""/local/localhost → localhost | machine_ips.json 의 키 → 그 .ip | 그 외 → 원문(IP/호스트).
_runlib::_default_machine_json() {
  local repo_root; repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  echo "$repo_root/shared/machine_ips.json"
}
_runlib::resolve_control_token() {
  local tok="$1" json="${2:-}"
  case "$tok" in ""|local|localhost) echo "localhost"; return 0 ;; esac
  [[ -z "$json" ]] && json="$(_runlib::_default_machine_json)"
  if [[ -f "$json" ]] && command -v jq >/dev/null 2>&1 \
     && jq -e --arg n "$tok" 'has($n)' "$json" >/dev/null 2>&1; then
    _runlib::lookup_machine_ip "$tok" "$json"   # 못 찾으면 stderr 안내 + return 1
    return
  fi
  echo "$tok"   # IP/호스트 직접 지정으로 간주
}

# choose_control_host [label] [json_path] → host 를 stdout 으로 (메뉴/프롬프트는 stderr).
# machine_ips.json 의 non-null 머신 + localhost + 수동입력 + 재스캔.
_runlib::choose_control_host() {
  local label="${1:-Control 서버}" json="${2:-}"
  [[ -z "$json" ]] && json="$(_runlib::_default_machine_json)"
  local script_dir; script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  while true; do
    local names=() ips=()
    if [[ -f "$json" ]] && command -v jq >/dev/null 2>&1; then
      mapfile -t names < <(jq -r 'to_entries[]|select(.value.ip!=null)|.key'      "$json" 2>/dev/null)
      mapfile -t ips   < <(jq -r 'to_entries[]|select(.value.ip!=null)|.value.ip' "$json" 2>/dev/null)
    fi
    {
      echo "=== $label 선택 ==="
      echo "  1) localhost            (이 머신에서 control 서버도 같이 돌릴 때)"
      local i
      for i in "${!names[@]}"; do
        printf "  %d) %-12s %s\n" "$((i + 2))" "${names[$i]}" "${ips[$i]}"
      done
      echo "  m) 수동 입력 (IP/호스트)"
      echo "  r) 재스캔 (find_machine_ips.sh — IP 갱신)"
    } >&2
    local choice
    read -rp "선택 [1/번호/m/r]: " choice >&2
    case "$choice" in
      1|"") echo "localhost"; return 0 ;;
      m|M)
        local h; read -rp "  IP/호스트: " h >&2
        [[ -n "$h" ]] && { echo "$h"; return 0; }
        ;;
      r|R)
        echo "[run_lib] find_machine_ips.sh 재실행..." >&2
        "$script_dir/find_machine_ips.sh" >/dev/null 2>&1 || true
        continue
        ;;
      *)
        if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 2 && choice - 2 < ${#names[@]} )); then
          echo "${ips[$((choice - 2))]}"; return 0
        fi
        echo "  잘못된 선택: $choice" >&2
        ;;
    esac
  done
}
