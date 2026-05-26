#!/usr/bin/env bash
# 9 plugin combo × N rep 자동 실행 (한 vertex 조건).
#
# 환경 :
#   sc_sim (device-gogoping-sim.sh up) 의 tmux 기반 풀스택 사용.
#   gazebo + nav2 + graph_router + modes(FSM) + sim_battery + sim_teleport + camera + rviz
#   — 실제 production 환경과 동일.
#
# 사용 :
#   bash run_all.sh                                # 9 × 3 = 27 runs (~2시간)
#   bash run_all.sh --reps 1                       # smoke test (9 runs, ~30분)
#   bash run_all.sh --reps 1 --controllers "RPP DWB"   # MPPI 제외 (6 runs)
#   bash run_all.sh --label sparse --reps 3        # 폴더명 라벨
#
# 사전 :
#   - 호출 셸에 ROS_DOMAIN_ID 설정 (보통 209)
#   - workspace install 소싱 (gogoping_msgs / colcon build 완료)
#   - conda env (jazzy) 활성화
#   - tmux 설치 (sc_sim 의존)
#   - topic_tools 설치 (relay 의존) — 'ros-jazzy-topic-tools'
#
# 동작 :
#   for combo in 선택된 PLANNER × CONTROLLER:
#     1. nav2 yaml swap (params/nav2_${P}_${C}.yaml → src/.../nav2_params_sim.yaml)
#     2. 기존 sc_sim 세션 정리 (device-gogoping-sim.sh down)
#     3. sc_sim 시작 (device-gogoping-sim.sh up) — detached, tmux 세션
#     4. nav2 lifecycle active 대기
#     5. cmd_vel relay 시작 (perception safety_filter 우회 — TODO: 정상 fix)
#     6. plugin verify
#     7. for rep in 1..N:
#          python3 run_one.py --run-id ${P}_${C}_rep${R} --skip-teleport
#
# Ctrl+C 시 : cleanup trap → sc_sim down + relay 종료 + 원본 yaml 복원
#
# 산출 :
#   /tmp/runs/<label>/<P>_<C>_rep<R>/bag/         ← rosbag2 mcap
#   /tmp/runs/<label>/<P>_<C>_rep<R>/metadata.json
#   /tmp/runs/<label>/run_all.log                  ← 실행 로그
#   /tmp/runs/<label>/run_summary.txt              ← CSV 요약

set -uo pipefail

# ───────────────────────────── 인자 ─────────────────────────────
REPS=3
LABEL="dense"
DESTINATION="수면실"
SIM_BOOT_WAIT=30           # device-gogoping-sim.sh up 후 tmux 세션 + nav2 부팅 대기
NAV2_READY_TIMEOUT=120
PLANNER_FILTER=""
CONTROLLER_FILTER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --reps) REPS="$2"; shift 2;;
        --label) LABEL="$2"; shift 2;;
        --destination) DESTINATION="$2"; shift 2;;
        --sim-wait) SIM_BOOT_WAIT="$2"; shift 2;;
        --planners) PLANNER_FILTER="$2"; shift 2;;
        --controllers) CONTROLLER_FILTER="$2"; shift 2;;
        -h|--help)
            sed -n '2,42p' "$0" | sed 's/^# \{0,1\}//'
            exit 0;;
        *) echo "unknown arg: $1" >&2; exit 1;;
    esac
done

# ───────────────────────────── 경로 ─────────────────────────────
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
RUN_ONE="${HERE}/run_one.py"
PARAMS_DIR="${HERE}/params"
NAV2_DEST="$REPO_ROOT/controller/gogoping-controller/src/gogoping/gogoping_navigation/params/nav2_params_sim.yaml"
SIM_SCRIPT="$REPO_ROOT/scripts/device-gogoping-sim.sh"
BACKUP="/tmp/nav2_params_sim_run_all_backup.yaml"
OUT_BASE="/tmp/runs/${LABEL}"
TMUX_SESSION="gogoping-sim"

mkdir -p "$OUT_BASE"
LOG="${OUT_BASE}/run_all.log"
SUMMARY="${OUT_BASE}/run_summary.txt"

# ───────────────────────────── 후보 ─────────────────────────────
ALL_PLANNERS=(NavFn Smac2D ThetaStar)
ALL_CONTROLLERS=(RPP DWB MPPI)

if [[ -n "$PLANNER_FILTER" ]]; then
    read -r -a PLANNERS <<< "$PLANNER_FILTER"
else
    PLANNERS=("${ALL_PLANNERS[@]}")
fi
if [[ -n "$CONTROLLER_FILTER" ]]; then
    read -r -a CONTROLLERS <<< "$CONTROLLER_FILTER"
else
    CONTROLLERS=("${ALL_CONTROLLERS[@]}")
fi

# ───────────────────────────── 로거 ─────────────────────────────
log() {
    local msg="[$(date '+%H:%M:%S')] $*"
    echo "$msg" | tee -a "$LOG"
}

# ───────────────────────────── 프로세스 핸들 ─────────────────────────────
RELAY_PID=""

cleanup() {
    log "── cleanup 시작 ──"
    stop_relay
    stop_sc_sim
    # 원본 yaml 복원
    if [[ -f "$BACKUP" ]]; then
        cp "$BACKUP" "$NAV2_DEST"
        log "원본 yaml 복원"
    fi
    log "── cleanup 완료 ──"
}
trap cleanup EXIT INT TERM

# ───────────────────────────── sc_sim 헬퍼 ─────────────────────────────

start_sc_sim() {
    log "sc_sim up (tmux 세션 '$TMUX_SESSION') 시작…"
    # `device-gogoping-sim.sh up` 는 마지막에 `exec tmux attach` 함.
    # nohup + </dev/null 으로 TTY 없이 background 실행 → attach 실패해도 tmux 세션은 살아있음.
    nohup bash "$SIM_SCRIPT" up </dev/null >>"${OUT_BASE}/sc_sim_up.log" 2>&1 &
    disown
    log "sc_sim spawn 완료, ${SIM_BOOT_WAIT}s 대기…"
    sleep "$SIM_BOOT_WAIT"

    # tmux 세션 존재 확인
    if ! tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
        log "❌ tmux 세션 '$TMUX_SESSION' 생성 실패 — sc_sim_up.log 확인"
        return 1
    fi
    log "tmux 세션 확인 OK"
    return 0
}

stop_sc_sim() {
    log "sc_sim down 실행…"
    bash "$SIM_SCRIPT" down >>"${OUT_BASE}/sc_sim_down.log" 2>&1 || true
    sleep 3
}

# ───────────────────────────── relay ─────────────────────────────

start_relay() {
    log "relay (cmd_vel_raw → cmd_vel) 시작…"
    nohup ros2 run topic_tools relay /gogoping/cmd_vel_raw /gogoping/cmd_vel \
        </dev/null >>"${OUT_BASE}/relay.log" 2>&1 &
    RELAY_PID=$!
    disown
    sleep 2
}

stop_relay() {
    if [[ -n "$RELAY_PID" ]]; then
        kill -INT "$RELAY_PID" 2>/dev/null || true
        sleep 1
        kill -KILL "$RELAY_PID" 2>/dev/null || true
        RELAY_PID=""
    fi
    pkill -INT -f "ros2 run topic_tools relay" 2>/dev/null || true
}

# ───────────────────────────── nav2 ready ─────────────────────────────

wait_for_nav2_active() {
    log "waiting for /bt_navigator active (timeout=${NAV2_READY_TIMEOUT}s)…"
    for ((i=1; i<=NAV2_READY_TIMEOUT; i++)); do
        local state
        state="$(ros2 lifecycle get /bt_navigator 2>/dev/null | head -1)"
        if [[ "$state" == "active [3]" ]]; then
            log "/bt_navigator active 도달 (${i}s)"
            return 0
        fi
        sleep 1
    done
    log "❌ /bt_navigator active 도달 실패 (timeout)"
    return 1
}

verify_plugin() {
    local expected_substring="$1"
    local plugin
    plugin="$(ros2 param get /controller_server FollowPath.plugin 2>&1 | tail -1)"
    if [[ "$plugin" == *"$expected_substring"* ]]; then
        log "plugin 확인: $plugin"
        return 0
    fi
    log "❌ plugin mismatch — expected $expected_substring, got $plugin"
    return 1
}

# ───────────────────────────── 시작 ─────────────────────────────
log "================================================="
log "run_all.sh — label=${LABEL}, reps=${REPS}"
log "planners   : ${PLANNERS[*]}"
log "controllers: ${CONTROLLERS[*]}"
log "총 ${#PLANNERS[@]} × ${#CONTROLLERS[@]} × ${REPS} = $(( ${#PLANNERS[@]} * ${#CONTROLLERS[@]} * REPS )) runs"
log "================================================="

# 백업
cp "$NAV2_DEST" "$BACKUP"
log "yaml backup → $BACKUP"

# 요약 헤더
echo "# run_summary — label=${LABEL}, reps=${REPS}, started=$(date)" > "$SUMMARY"
echo "# planner,controller,rep,exit_code,duration_s,run_id" >> "$SUMMARY"

CELL_IDX=0
TOTAL_CELLS=$(( ${#PLANNERS[@]} * ${#CONTROLLERS[@]} ))

for P in "${PLANNERS[@]}"; do
    for C in "${CONTROLLERS[@]}"; do
        CELL_IDX=$(( CELL_IDX + 1 ))
        log ""
        log "═══════════════════════════════════════════════════"
        log "  cell ${CELL_IDX}/${TOTAL_CELLS} — Planner=${P}, Controller=${C}"
        log "═══════════════════════════════════════════════════"

        # 1. yaml swap
        SRC_YAML="${PARAMS_DIR}/nav2_${P}_${C}.yaml"
        if [[ ! -f "$SRC_YAML" ]]; then
            log "❌ yaml 없음: $SRC_YAML — cell skip"
            continue
        fi
        cp "$SRC_YAML" "$NAV2_DEST"
        log "yaml swap → ${P}_${C}"

        # 2. sc_sim 재시작
        stop_relay
        stop_sc_sim
        if ! start_sc_sim; then
            log "❌ ${P}_${C}: sc_sim 시작 실패 — cell skip"
            continue
        fi
        if ! wait_for_nav2_active; then
            log "❌ ${P}_${C}: nav2 not ready — cell skip"
            continue
        fi
        start_relay

        # 3. plugin verify
        EXPECTED_HINT=""
        case "$C" in
            RPP)  EXPECTED_HINT="regulated_pure_pursuit" ;;
            DWB)  EXPECTED_HINT="DWBLocalPlanner" ;;
            MPPI) EXPECTED_HINT="MPPIController" ;;
        esac
        if [[ -n "$EXPECTED_HINT" ]]; then
            if ! verify_plugin "$EXPECTED_HINT"; then
                log "❌ ${P}_${C}: plugin verify 실패 — cell skip"
                continue
            fi
        fi

        # 4. reps
        for ((R=1; R<=REPS; R++)); do
            RUN_ID="${P}_${C}_rep${R}"
            log "──────  run ${RUN_ID}  ──────"
            START=$(date +%s)
            python3 "$RUN_ONE" \
                --run-id "$RUN_ID" \
                --output-dir "$OUT_BASE" \
                --destination "$DESTINATION" \
                --skip-teleport \
                2>&1 | tee -a "$LOG"
            RC=${PIPESTATUS[0]}
            END=$(date +%s)
            DUR=$(( END - START ))
            echo "${P},${C},${R},${RC},${DUR},${RUN_ID}" >> "$SUMMARY"
            log "→ ${RUN_ID}: exit=${RC}, duration=${DUR}s"
            sleep 3
        done
    done
done

log ""
log "════════════════════════════════════════════"
log "  완료 — 총 ${TOTAL_CELLS} cells, ${REPS} reps each"
log "  summary : ${SUMMARY}"
log "  bags    : ${OUT_BASE}/*/bag/"
log "════════════════════════════════════════════"
