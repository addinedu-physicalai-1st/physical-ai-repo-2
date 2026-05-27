#!/usr/bin/env bash
# 81 runs full experiment 한 호흡 실행.
#
#   Phase 1 : Dense  (27 runs, 35 vertex)
#   Phase 2 : Mid swap
#   Phase 3 : Mid    (27 runs, 17 vertex)
#   Phase 4 : Sparse swap
#   Phase 5 : Sparse (27 runs, 14 vertex)
#   Phase 6 : Dense 복원
#   Phase 7 : 분석 CSV/table 출력
#
# 사용:
#   bash run_full_experiment.sh                       # 81 runs (~5시간)
#   bash run_full_experiment.sh --reps 1              # smoke 27 runs (~1.7시간)
#   bash run_full_experiment.sh --controllers "RPP DWB"   # MPPI 제외 (54 runs)
#
# 사전 :
#   - source /opt/ros/jazzy/setup.zsh
#   - source ~/pingdergarten/install/local_setup.zsh
#   - conda activate jazzy
#   - export ROS_DOMAIN_ID=209
#
# 종료 처리 :
#   - Ctrl+C 시 trap → vertex Dense 자동 복원
#   - 각 Phase 실패 시 다음 Phase 계속 진행 (전체 중단 X)

set -uo pipefail

# ────────────── 인자 ──────────────
REPS=3
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --reps) REPS="$2"; shift 2;;
        --controllers) EXTRA_ARGS+=("--controllers" "$2"); shift 2;;
        --planners) EXTRA_ARGS+=("--planners" "$2"); shift 2;;
        -h|--help)
            sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
            exit 0;;
        *) echo "unknown arg: $1" >&2; exit 1;;
    esac
done

# ────────────── 경로 ──────────────
HERE="$(cd "$(dirname "$0")" && pwd)"
MASTER_LOG="/tmp/runs/full_experiment.log"
mkdir -p /tmp/runs

# ────────────── 로거 ──────────────
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$MASTER_LOG"
}

# ────────────── 안전 trap ──────────────
on_exit() {
    log ""
    log "━━━ exit trap — Dense 복원 시도 ━━━"
    bash "$HERE/swap_vertex.sh" dense 2>&1 | tee -a "$MASTER_LOG" || true
    log "━━━ exit trap 완료 ━━━"
}
trap on_exit EXIT INT TERM

# ────────────── Phase helpers ──────────────
run_phase() {
    local label="$1"
    local phase_no="$2"
    log ""
    log "════════ Phase ${phase_no}/7 : ${label} 실험 시작 ════════"
    local start=$(date +%s)
    bash "$HERE/run_all.sh" --reps "$REPS" --label "$label" "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}" \
        2>&1 | tee -a "$MASTER_LOG"
    local rc=${PIPESTATUS[0]}
    local dur=$(( $(date +%s) - start ))
    log "Phase ${phase_no} 완료 — exit=${rc}, duration=${dur}s ($(( dur / 60 ))분)"
    return $rc
}

swap_to() {
    local mode="$1"
    local phase_no="$2"
    log ""
    log "════════ Phase ${phase_no}/7 : ${mode} vertex 적용 ════════"
    bash "$HERE/swap_vertex.sh" "$mode" 2>&1 | tee -a "$MASTER_LOG"
    return $?
}

analyze_label() {
    local label="$1"
    if [[ -d "/tmp/runs/${label}" ]]; then
        # 전체 (timeout 포함)
        python3 "$HERE/analysis/compare_runs.py" "/tmp/runs/${label}" --csv > "/tmp/runs/${label}.csv" 2>>"$MASTER_LOG" \
            && log "✅ /tmp/runs/${label}.csv 생성"
        python3 "$HERE/analysis/compare_runs.py" "/tmp/runs/${label}" > "/tmp/runs/${label}_table.txt" 2>>"$MASTER_LOG" \
            && log "✅ /tmp/runs/${label}_table.txt 생성"
        # 완주 only
        python3 "$HERE/analysis/compare_runs.py" "/tmp/runs/${label}" --completed-only \
            > "/tmp/runs/${label}_completed.txt" 2>>"$MASTER_LOG" \
            && log "✅ /tmp/runs/${label}_completed.txt 생성"
        # 실패 forensics
        python3 "$HERE/analysis/compare_runs.py" "/tmp/runs/${label}" --failure-report \
            > "/tmp/runs/${label}_failures.txt" 2>>"$MASTER_LOG" \
            && log "✅ /tmp/runs/${label}_failures.txt 생성"
    fi
}

# ────────────── 시작 ──────────────
log "════════════════════════════════════════════════"
log "  Full Experiment — 81 runs (or filtered)"
log "  reps=${REPS}  extra=${EXTRA_ARGS[*]:-all}"
log "  log: $MASTER_LOG"
log "════════════════════════════════════════════════"

# Pre-check
log "─── Pre-check ───"
if ! command -v ros2 >/dev/null; then
    log "❌ ros2 not in PATH — source 안 됐음"
    exit 1
fi
if [[ -z "${ROS_DOMAIN_ID:-}" ]]; then
    log "❌ ROS_DOMAIN_ID 미설정"
    exit 1
fi
log "ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
log "PWD=$HERE"
START_EPOCH=$(date +%s)

# ────────────── Phase 1 : Dense ──────────────
# 현재 canonical 이 dense 라고 가정 (run_full_experiment 가 끝나면 trap 이 dense 복원)
swap_to dense 0 || true   # 안전: 시작 시 dense 보장
run_phase dense 1 || true

# ────────────── Phase 2 : Mid swap ──────────────
SKIP_MID=0
swap_to mid 2 || { log "❌ swap mid 실패 — Phase 3 건너뜀"; SKIP_MID=1; }

# ────────────── Phase 3 : Mid ──────────────
if [[ $SKIP_MID -eq 0 ]]; then
    run_phase mid 3 || true
fi

# ────────────── Phase 4 : Sparse swap ──────────────
SKIP_SPARSE=0
swap_to sparse 4 || { log "❌ swap sparse 실패 — Phase 5 건너뜀"; SKIP_SPARSE=1; }

# ────────────── Phase 5 : Sparse ──────────────
if [[ $SKIP_SPARSE -eq 0 ]]; then
    run_phase sparse 5 || true
fi

# ────────────── Phase 6 : Dense 복원 ──────────────
log ""
log "════════ Phase 6/7 : Dense 복원 ════════"
bash "$HERE/swap_vertex.sh" dense 2>&1 | tee -a "$MASTER_LOG" || true

# ────────────── Phase 7 : 분석 ──────────────
log ""
log "════════ Phase 7/7 : 분석 CSV/table 생성 ════════"
analyze_label dense
[[ $SKIP_MID -eq 0 ]] && analyze_label mid
[[ $SKIP_SPARSE -eq 0 ]] && analyze_label sparse

# ────────────── 최종 요약 ──────────────
TOTAL_DUR=$(( $(date +%s) - START_EPOCH ))
log ""
log "════════════════════════════════════════════════"
log "  Full Experiment 완료"
log "  총 소요 : $(( TOTAL_DUR / 60 ))분 $(( TOTAL_DUR % 60 ))초"
log "  산출    :"
log "    /tmp/runs/dense/   ($(ls /tmp/runs/dense  2>/dev/null | grep -c rep) runs)"
log "    /tmp/runs/mid/     ($(ls /tmp/runs/mid    2>/dev/null | grep -c rep) runs)"
log "    /tmp/runs/sparse/  ($(ls /tmp/runs/sparse 2>/dev/null | grep -c rep) runs)"
log "    /tmp/runs/{dense,mid,sparse}.csv + _table.txt"
log "    /tmp/runs/full_experiment.log"
log "════════════════════════════════════════════════"

# trap 이 dense 복원 다시 시도 — 무해
