#!/usr/bin/env bash
# 같은 LAN 안에 있는 머신들의 IP 를 MAC 주소로 찾아 shared/machine_ips.json 에 저장.
# 동작: 기본 인터페이스의 서브넷을 자동 감지 → nmap -sn ping sweep →
#       ip neigh 로 MAC->IP 매핑 추출 → JSON 작성.
# 못 찾은 머신은 ip=null 로 두고 stderr 에 에러 메시지를 출력.
# 한 머신이라도 못 찾으면 exit 1.

set -euo pipefail

declare -A MACS=(
  [vic]="2c:cf:67:e7:ee:29"
  [leekt]="e8:65:38:23:73:f1"
  [tonyno]="e4:c7:67:61:2f:2e"
  [jungbuntu]="e8:65:38:23:fd:6f"   # backend (DB + AI Hub)
  [ai-server]="10:ff:e0:8d:a1:2a"   # woolim — AI Hub / DB (run_db_ai.sh)
  [hajuntu]="84:1b:77:04:24:a5"    # 의사 머신 + 리드디바이스 (run_server + device-doctor) — control 서버 :8000 호스트
)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/shared"
OUT_FILE="$OUT_DIR/machine_ips.json"

for cmd in nmap ip jq awk; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: required command '$cmd' not found in PATH" >&2
    exit 1
  fi
done

mkdir -p "$OUT_DIR"

default_iface="$(ip route show default 2>/dev/null | awk '/^default/ {print $5; exit}')"
if [[ -z "${default_iface:-}" ]]; then
  echo "Error: failed to detect default network interface" >&2
  exit 1
fi

subnet="$(ip -4 -o addr show dev "$default_iface" | awk '{print $4; exit}')"
if [[ -z "${subnet:-}" ]]; then
  echo "Error: failed to detect IPv4 subnet on '$default_iface'" >&2
  exit 1
fi

# 자기 머신의 인터페이스 MAC -> IPv4 매핑 (ARP 로는 자기 자신을 못 찾음)
declare -A LOCAL_TABLE
while read -r iface mac; do
  [[ -z "$iface" || -z "$mac" ]] && continue
  mac_lc="$(echo "$mac" | tr 'A-Z' 'a-z')"
  local_ip="$(ip -4 -o addr show dev "$iface" scope global 2>/dev/null \
              | awk 'NR==1 {split($4,a,"/"); print a[1]}')"
  [[ -n "$local_ip" ]] && LOCAL_TABLE["$mac_lc"]="$local_ip"
done < <(ip -o link show | awk '
  {
    iface = $2; sub(/:$/, "", iface); sub(/@.*/, "", iface);
    for (i = 1; i <= NF; i++) if ($i == "link/ether") { print iface, $(i+1); break }
  }')

echo "Scanning $subnet on $default_iface ..." >&2
nmap -sn -T4 -n --max-retries 1 "$subnet" >/dev/null

declare -A ARP_TABLE
while read -r line; do
  ip_addr="$(awk '{print $1}' <<<"$line")"
  mac="$(awk '{for(i=1;i<=NF;i++) if($i=="lladdr") {print $(i+1); exit}}' <<<"$line" | tr 'A-Z' 'a-z')"
  if [[ -n "$ip_addr" && -n "$mac" && "$mac" != "<incomplete>" ]]; then
    ARP_TABLE["$mac"]="$ip_addr"
  fi
done < <(ip neigh show)

timestamp="$(date -Iseconds)"
tmp_json="$(mktemp)"
echo "{}" > "$tmp_json"

missing=0
for name in "${!MACS[@]}"; do
  mac_lc="$(echo "${MACS[$name]}" | tr 'A-Z' 'a-z')"
  ip_addr="${LOCAL_TABLE[$mac_lc]:-${ARP_TABLE[$mac_lc]:-}}"
  if [[ -z "$ip_addr" ]]; then
    echo "Error: could not find IP for '$name' (mac=$mac_lc) on $subnet" >&2
    missing=1
    jq --arg name "$name" --arg mac "$mac_lc" --arg ts "$timestamp" \
       '.[$name] = {mac: $mac, ip: null, found_at: $ts}' \
       "$tmp_json" > "$tmp_json.new" && mv "$tmp_json.new" "$tmp_json"
  else
    jq --arg name "$name" --arg mac "$mac_lc" --arg ip "$ip_addr" --arg ts "$timestamp" \
       '.[$name] = {mac: $mac, ip: $ip, found_at: $ts}' \
       "$tmp_json" > "$tmp_json.new" && mv "$tmp_json.new" "$tmp_json"
  fi
done

mv "$tmp_json" "$OUT_FILE"
echo "Saved to $OUT_FILE" >&2
cat "$OUT_FILE"

exit "$missing"
