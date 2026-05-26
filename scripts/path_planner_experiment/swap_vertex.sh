#!/usr/bin/env bash
# Dense ↔ Sparse vertex 설정 swap.
#
# Dense  : 35 vertex (원본 waypoints.yaml / lanes.yaml)
# Sparse : 7 vertex (waypoints/sparse_waypoints.yaml / sparse_lanes.yaml)
#
# 사용 :
#   bash swap_vertex.sh sparse    # Sparse 로 전환
#   bash swap_vertex.sh dense     # Dense (원본) 복원
#   bash swap_vertex.sh status    # 현재 상태 확인
#
# 동작 :
#   - controller/.../config/{waypoints,lanes}.yaml 을 백업 후 교체
#   - 백업 위치 : /tmp/vertex_backup/{waypoints,lanes}.yaml
#   - graph_router 가 재시작될 때 새 graph 로드 (sim 재시작 필요)

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
CONFIG_DIR="$REPO/controller/gogoping-controller/src/gogoping/gogoping_navigation/config"
WP_DEST="$CONFIG_DIR/waypoints.yaml"
LN_DEST="$CONFIG_DIR/lanes.yaml"
SPARSE_WP="$HERE/waypoints/sparse_waypoints.yaml"
SPARSE_LN="$HERE/waypoints/sparse_lanes.yaml"
BACKUP_DIR="/tmp/vertex_backup"
WP_BACKUP="$BACKUP_DIR/waypoints.yaml"
LN_BACKUP="$BACKUP_DIR/lanes.yaml"
STATE_FILE="$BACKUP_DIR/state"

mode="${1:-status}"

mkdir -p "$BACKUP_DIR"

count_vertices() {
    local f="$1"
    grep -c "^- name:" "$f" 2>/dev/null || echo 0
}

case "$mode" in
    sparse)
        if [[ ! -f "$WP_BACKUP" ]]; then
            cp "$WP_DEST" "$WP_BACKUP"
            cp "$LN_DEST" "$LN_BACKUP"
            echo "백업 → $BACKUP_DIR/"
        fi
        cp "$SPARSE_WP" "$WP_DEST"
        cp "$SPARSE_LN" "$LN_DEST"
        echo "sparse" > "$STATE_FILE"
        echo "✅ Sparse 적용 — $(count_vertices "$WP_DEST") vertices"
        echo "   다음 sim 재시작부터 적용됨."
        ;;
    dense)
        if [[ ! -f "$WP_BACKUP" ]]; then
            echo "❌ 백업 없음 — 이미 dense 일 가능성. git checkout 으로 복원."
            exit 1
        fi
        cp "$WP_BACKUP" "$WP_DEST"
        cp "$LN_BACKUP" "$LN_DEST"
        echo "dense" > "$STATE_FILE"
        echo "✅ Dense 복원 — $(count_vertices "$WP_DEST") vertices"
        echo "   다음 sim 재시작부터 적용됨."
        ;;
    status)
        n=$(count_vertices "$WP_DEST")
        state=$(cat "$STATE_FILE" 2>/dev/null || echo "unknown")
        echo "현재 waypoints.yaml : ${n} vertices (state=${state})"
        if [[ -f "$WP_BACKUP" ]]; then
            echo "백업 존재    : $WP_BACKUP ($(count_vertices "$WP_BACKUP") vertices)"
        else
            echo "백업 없음 — sparse 적용된 적 없음"
        fi
        ;;
    *)
        echo "usage: $0 {sparse|dense|status}" >&2
        exit 1
        ;;
esac
