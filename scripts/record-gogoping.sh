#!/usr/bin/env bash
# scripts/record-gogoping.sh — GogoPing 시나리오 rosbag 녹화.
#
# 동작:
#   - log/rosbags/<YYYY-MM-DD_HH-MM-SS>[_label]/ 에 MCAP 포맷으로 저장
#   - 토픽 그룹 A (nav 표준) + B (GogoPing 디버그) 기본 포함
#   - C (카메라 서보) 는 --with-camera 플래그로 추가
#
# 사용:
#   scripts/record-gogoping.sh                                # 기본 (A+B)
#   scripts/record-gogoping.sh --name narrow_corridor_navfn   # 라벨 붙임
#   scripts/record-gogoping.sh --with-camera                  # + 카메라 서보
#   scripts/record-gogoping.sh --name narrow_smac --with-camera
#   scripts/record-gogoping.sh --help
#
# 의존:
#   - ROS 2 jazzy + `ros-jazzy-rosbag2-storage-mcap` apt 패키지
#   - `source /opt/ros/jazzy/setup.{bash,zsh}` + 우리 워크스페이스 setup
#     (보통 setup.zsh 가 둘 다 source 함)
#   - ROS_DOMAIN_ID 가 디바이스/팀원과 동일하게 설정돼있어야 함 (201~219)
#
# 정지:
#   Ctrl+C — ros2 bag 이 graceful 하게 close, metadata.yaml 작성 완료 후 종료.
#
# Foxglove 로 열기:
#   - https://foxglove.dev 에서 Foxglove Studio 다운로드 (무료)
#   - Open file → log/rosbags/<...>/<...>.mcap 선택
#   - 또는 ros2 bag play log/rosbags/<...>/ 로 토픽 재생
#
# 참고: incident 발생 직후 동시에 NavDebugLogCard 의 💾 (Export) 버튼으로
# nav_events 도 .jsonl 로 저장해두면, 같은 폴더에 두 증거가 모임.

set -euo pipefail

# ──────── 인자 파싱 ────────
LABEL=""
WITH_CAMERA=0

usage() {
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name)
            LABEL="$2"; shift 2;;
        --with-camera)
            WITH_CAMERA=1; shift;;
        -h|--help)
            usage;;
        *)
            echo "unknown arg: $1" >&2
            echo "see --help" >&2
            exit 1;;
    esac
done

# ──────── 환경 점검 ────────
if ! command -v ros2 >/dev/null 2>&1; then
    echo "ros2 not found — source /opt/ros/jazzy/setup.{bash,zsh} 먼저." >&2
    exit 1
fi

if [[ -z "${ROS_DOMAIN_ID:-}" ]]; then
    echo "WARN: ROS_DOMAIN_ID 미설정. 다른 팀원과 충돌할 수 있어요." >&2
    echo "      해결: export ROS_DOMAIN_ID=<201~219 중 본인 ID>" >&2
fi

# rosbag2 의 mcap storage plugin 확인
if ! ros2 bag info --help 2>&1 | grep -qE "storage" ; then
    echo "ros2 bag 명령이 비정상이에요." >&2
    exit 1
fi

# ──────── 저장 경로 ────────
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TS="$(date +%Y-%m-%d_%H-%M-%S)"
if [[ -n "$LABEL" ]]; then
    OUT_DIR="${REPO_ROOT}/log/rosbags/${TS}_${LABEL}"
else
    OUT_DIR="${REPO_ROOT}/log/rosbags/${TS}"
fi
mkdir -p "$(dirname "$OUT_DIR")"

# ──────── 토픽 그룹 ────────
# A. nav 표준 — Nav2 동작 재현 + 메트릭 계산에 필요한 최소 셋
TOPICS_NAV=(
    /scan
    /gogoping/scan
    /odom
    /tf
    /tf_static
    /cmd_vel
    /gogoping/cmd_vel
    /goal_pose
    /plan
    /local_plan
    /amcl_pose
    /initialpose
)

# B. GogoPing 디버그 — 우리 11 source 통합 로그 + UI/state
TOPICS_DEBUG=(
    /gogoping/state
    /gogoping/debug/nav_events
    /gogoping/ui_event
    /gogoping/follow_target
    /gogoping/tracking_state
    /gogoping/battery
)

# C. 카메라 서보 — --with-camera 시만
TOPICS_CAMERA=(
    /servo_bridge/cmd_pan
    /servo_bridge/cmd_tilt
)

# 합치기
TOPICS=("${TOPICS_NAV[@]}" "${TOPICS_DEBUG[@]}")
if [[ $WITH_CAMERA -eq 1 ]]; then
    TOPICS+=("${TOPICS_CAMERA[@]}")
fi

# ──────── 사전 안내 ────────
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  GogoPing rosbag recording"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  output:    ${OUT_DIR}"
echo "  domain:    ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-<unset>}"
echo "  topics:    ${#TOPICS[@]}개 (camera $([[ $WITH_CAMERA -eq 1 ]] && echo on || echo off))"
echo "  storage:   mcap"
echo "  stop:      Ctrl+C"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo

# ──────── 녹화 시작 ────────
# -s mcap: 저장 형식 (Foxglove native)
# --no-discovery: 토픽 자동 디스커버리 비활성 — 우리가 지정한 토픽 외엔 안 받음
#                (실수로 다른 토픽 잡혀서 bag 부풀어지는 거 방지)
exec ros2 bag record \
    -s mcap \
    -o "$OUT_DIR" \
    "${TOPICS[@]}"
