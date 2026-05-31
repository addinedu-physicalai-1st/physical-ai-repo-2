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

# ───────────── 워크스페이스 install 자동 소싱 ─────────────
# 사용자 셸에서 source 안 됐을 경우 대비 — gogoping_msgs import 보장.
# ros setup.bash 가 unbound var 참조 → set -u 잠시 끄고 source.
if ! python3 -c "from gogoping_msgs.srv import SetGoal" 2>/dev/null; then
    set +u
    if [[ -f /opt/ros/jazzy/setup.bash ]]; then
        # shellcheck disable=SC1091
        source /opt/ros/jazzy/setup.bash
    fi
    if [[ -f "$HOME/pingdergarten/install/local_setup.bash" ]]; then
        # shellcheck disable=SC1091
        source "$HOME/pingdergarten/install/local_setup.bash"
    fi
    set -u
    if ! python3 -c "from gogoping_msgs.srv import SetGoal" 2>/dev/null; then
        echo "❌ gogoping_msgs import 실패 — 워크스페이스 build 필요 또는 PYTHONPATH 문제" >&2
        echo "   cd ~/pingdergarten && colcon build --symlink-install" >&2
        exit 1
    fi
fi

# ───────────────────────────── 인자 ─────────────────────────────
REPS=3
START_REP=1                # 이어쌓기: rep 시작번호 (--start-rep 2 면 rep2~REPS → 기존 rep1 보존)
ROUTE="수면실,놀이방,놀이방입구-하"          # 다단계 GOTO 순서 (run_scenario.py)
RESULTS_DIR="/home/leekt/발표자료/실험 결과물"  # per-run txt/json/bags + 로그 (= /tmp 아님)
LABEL="dense"
DESTINATION="수면실"
SIM_BOOT_WAIT=20           # device-gogoping-sim.sh up 후 tmux 세션 + nav2 부팅 대기
NAV2_READY_TIMEOUT=240
PLANNER_FILTER=""
CONTROLLER_FILTER=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --reps|--steps) REPS="$2"; shift 2;;
        --start-rep) START_REP="$2"; shift 2;;
        --route) ROUTE="$2"; shift 2;;
        --results-dir) RESULTS_DIR="$2"; shift 2;;
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
RUN_SCENARIO="${HERE}/run_scenario.py"
PARAMS_DIR="${HERE}/params"
NAV2_DEST="$REPO_ROOT/controller/gogoping-controller/src/gogoping/gogoping_navigation/params/nav2_params_sim.yaml"
SIM_SCRIPT="$REPO_ROOT/scripts/device-gogoping-sim.sh"
BACKUP="/tmp/nav2_params_sim_run_all_backup.yaml"
OUT_BASE="${RESULTS_DIR}"            # run_all 로그/요약 + (run_scenario 가) per-run txt/json/bags
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
    timeout 30 bash "$SIM_SCRIPT" down >>"${OUT_BASE}/sc_sim_down.log" 2>&1 || true
    sleep 2

    # DDS participant slot 누적 방지 — 좀비 / orphan KILL.
    # "Failed to find a free participant index" 에러 예방.
    pkill -KILL -f "ros2 run topic_tools" 2>/dev/null || true
    pkill -KILL -f "topic_tools/relay" 2>/dev/null || true
    pkill -KILL -f "rosbag2_recorder" 2>/dev/null || true
    pkill -KILL -f "ros2 launch gogoping" 2>/dev/null || true
    pkill -KILL -f "ros2 run gogoping" 2>/dev/null || true
    pkill -KILL -f "amcl" 2>/dev/null || true
    pkill -KILL -f "controller_server" 2>/dev/null || true
    pkill -KILL -f "planner_server" 2>/dev/null || true
    pkill -KILL -f "behavior_server" 2>/dev/null || true
    pkill -KILL -f "bt_navigator" 2>/dev/null || true
    pkill -KILL -f "lifecycle_manager" 2>/dev/null || true
    pkill -KILL -f "map_server" 2>/dev/null || true
    pkill -KILL -f "waypoint_follower" 2>/dev/null || true
    pkill -KILL -f "velocity_smoother" 2>/dev/null || true
    pkill -KILL -f "robot_state_publisher" 2>/dev/null || true
    pkill -KILL -f "parameter_bridge" 2>/dev/null || true
    pkill -KILL -f "scan_to_scan_filter" 2>/dev/null || true

    # ros2 daemon 도 재시작 — 좀비 participant 의 stale 정보 제거.
    timeout 10 ros2 daemon stop 2>/dev/null || true
    sleep 1
    timeout 10 ros2 daemon start 2>/dev/null || true
    sleep 2
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
        kill -KILL "$RELAY_PID" 2>/dev/null || true
        RELAY_PID=""
    fi
    # 누적 방지 — relay 의 python wrapper + C++ 바이너리 둘 다 KILL.
    pkill -KILL -f "ros2 run topic_tools relay" 2>/dev/null || true
    pkill -KILL -f "topic_tools/relay" 2>/dev/null || true
    sleep 0.5
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
log "run_all.sh — label=${LABEL}, reps=${START_REP}..${REPS}"
log "planners   : ${PLANNERS[*]}"
log "controllers: ${CONTROLLERS[*]}"
log "총 ${#PLANNERS[@]} × ${#CONTROLLERS[@]} × $(( REPS - START_REP + 1 )) = $(( ${#PLANNERS[@]} * ${#CONTROLLERS[@]} * (REPS - START_REP + 1) )) runs"
log "================================================="

# 백업
cp "$NAV2_DEST" "$BACKUP"
log "yaml backup → $BACKUP"

# 요약 헤더 — 이어쌓기(파일 이미 있음)면 append, 처음이면 새로 생성
if [[ -f "$SUMMARY" ]]; then
    echo "# ── append batch: reps ${START_REP}..${REPS}, started=$(date)" >> "$SUMMARY"
else
    echo "# run_summary — label=${LABEL}, reps=${REPS}, started=$(date)" > "$SUMMARY"
    echo "# planner,controller,rep,exit_code,duration_s,run_id" >> "$SUMMARY"
fi

CELL_IDX=0
TOTAL_CELLS=$(( ${#PLANNERS[@]} * ${#CONTROLLERS[@]} ))

for P in "${PLANNERS[@]}"; do
    for C in "${CONTROLLERS[@]}"; do
        CELL_IDX=$(( CELL_IDX + 1 ))
        log ""
        log "═══════════════════════════════════════════════════"
        log "  cell ${CELL_IDX}/${TOTAL_CELLS} — Planner=${P}, Controller=${C}"
        log "═══════════════════════════════════════════════════"

        # yaml swap (cell 1회만 — 같은 plugin 으로 N reps)
        SRC_YAML="${PARAMS_DIR}/nav2_${P}_${C}.yaml"
        if [[ ! -f "$SRC_YAML" ]]; then
            log "❌ yaml 없음: $SRC_YAML — cell skip"
            continue
        fi
        cp "$SRC_YAML" "$NAV2_DEST"
        log "yaml swap → ${P}_${C}"

        EXPECTED_HINT=""
        case "$C" in
            RPP)  EXPECTED_HINT="regulated_pure_pursuit" ;;
            DWB)  EXPECTED_HINT="DWBLocalPlanner" ;;
            MPPI) EXPECTED_HINT="MPPIController" ;;
        esac

        # reps 마다 sim 재시작 — 깨끗한 환경 보장
        for ((R=START_REP; R<=REPS; R++)); do
            RUN_ID="${P}-${C}-${R}"   # = run_scenario 출력 파일명 ({planner}-{controller}-{rep})
            log ""
            log "──── rep ${R}/${REPS} : ${RUN_ID} ────"

            # 1. sim 재시작 (매 rep)
            stop_relay
            stop_sc_sim
            if ! start_sc_sim; then
                log "❌ ${RUN_ID}: sc_sim 시작 실패 — rep skip"
                echo "${P},${C},${R},99,0,${RUN_ID}" >> "$SUMMARY"
                continue
            fi
            if ! wait_for_nav2_active; then
                log "❌ ${RUN_ID}: nav2 not ready — rep skip"
                echo "${P},${C},${R},99,0,${RUN_ID}" >> "$SUMMARY"
                continue
            fi
            start_relay

            # 2. plugin verify (매 rep)
            if [[ -n "$EXPECTED_HINT" ]]; then
                if ! verify_plugin "$EXPECTED_HINT"; then
                    log "❌ ${RUN_ID}: plugin verify 실패 — rep skip"
                    echo "${P},${C},${R},98,0,${RUN_ID}" >> "$SUMMARY"
                    continue
                fi
            fi

            # 3. 1 run
            START=$(date +%s)
            python3 "$RUN_SCENARIO" \
                --planner "$P" --controller "$C" --rep "$R" \
                --route "$ROUTE" \
                --results-dir "$RESULTS_DIR" \
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
