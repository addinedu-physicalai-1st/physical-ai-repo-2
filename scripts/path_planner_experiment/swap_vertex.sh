#!/usr/bin/env bash
# Dense / Mid-Sparse / Sparse vertex 설정 swap.
#
# Dense      : 35 vertex (waypoints/dense_*.yaml)
# Mid-Sparse : 17 vertex (waypoints/mid_sparse_*.yaml)
# Sparse     : 14 vertex (waypoints/sparse_*.yaml)
#
# 사용 :
#   bash swap_vertex.sh dense     # Dense 적용
#   bash swap_vertex.sh mid       # Mid-Sparse 적용
#   bash swap_vertex.sh sparse    # Sparse 적용
#   bash swap_vertex.sh status    # 현재 상태 확인
#
# 동작 :
#   - controller/.../config/{waypoints,lanes}.yaml 을 source 파일로 교체
#   - graph_router 가 재시작될 때 새 graph 로드 (sim 재시작 필요)

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
CONFIG_DIR="$REPO/controller/gogoping-controller/src/gogoping/gogoping_navigation/config"
WP_DEST="$CONFIG_DIR/waypoints.yaml"
LN_DEST="$CONFIG_DIR/lanes.yaml"

DENSE_WP="$HERE/waypoints/dense_waypoints.yaml"
DENSE_LN="$HERE/waypoints/dense_lanes.yaml"
MID_WP="$HERE/waypoints/mid_sparse_waypoints.yaml"
MID_LN="$HERE/waypoints/mid_sparse_lanes.yaml"
SPARSE_WP="$HERE/waypoints/sparse_waypoints.yaml"
SPARSE_LN="$HERE/waypoints/sparse_lanes.yaml"

STATE_FILE="/tmp/vertex_backup/state"
mkdir -p "$(dirname "$STATE_FILE")"

count_vertices() {
    local f="$1"
    grep -c "^- name:" "$f" 2>/dev/null || echo 0
}

apply() {
    local label="$1" wp="$2" ln="$3"
    if [[ ! -f "$wp" ]] || [[ ! -f "$ln" ]]; then
        echo "❌ 소스 누락: $wp / $ln"
        exit 1
    fi
    cp "$wp" "$WP_DEST"
    cp "$ln" "$LN_DEST"
    echo "$label" > "$STATE_FILE"
    echo "✅ $label 적용 — $(count_vertices "$WP_DEST") vertex / $(grep -c '^- from:' "$LN_DEST") lane"
    echo "   다음 sim 재시작부터 적용됨."
}

mode="${1:-status}"

case "$mode" in
    dense)  apply dense  "$DENSE_WP"  "$DENSE_LN"  ;;
    mid)    apply mid    "$MID_WP"    "$MID_LN"    ;;
    sparse) apply sparse "$SPARSE_WP" "$SPARSE_LN" ;;
    status)
        n=$(count_vertices "$WP_DEST")
        l=$(grep -c '^- from:' "$LN_DEST" 2>/dev/null || echo 0)
        state=$(cat "$STATE_FILE" 2>/dev/null || echo "unknown")
        echo "현재 waypoints.yaml : ${n} vertex / ${l} lane (state=${state})"
        echo ""
        echo "사용 가능 set :"
        printf "  %-8s %s vertex / %s lane\n" dense  "$(count_vertices "$DENSE_WP")"  "$(grep -c '^- from:' "$DENSE_LN")"
        printf "  %-8s %s vertex / %s lane\n" mid    "$(count_vertices "$MID_WP")"    "$(grep -c '^- from:' "$MID_LN")"
        printf "  %-8s %s vertex / %s lane\n" sparse "$(count_vertices "$SPARSE_WP")" "$(grep -c '^- from:' "$SPARSE_LN")"
        ;;
    *)
        echo "usage: $0 {dense|mid|sparse|status}" >&2
        exit 1
        ;;
esac
