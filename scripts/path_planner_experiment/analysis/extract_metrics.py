#!/usr/bin/env python3
"""rosbag (.mcap) 1개 → 메트릭 + 신뢰도 점수 추출.

사용:
  python3 extract_metrics.py /tmp/runs/test_01/bag/bag_0.mcap
  python3 extract_metrics.py /tmp/runs/*/bag/*.mcap   # 여러 bag 비교

출력:
  사람이 읽기 좋은 표 + JSON (option --json)

메트릭:
  M2 duration       (s)
  M3 path length    (m)
  M4 avg/max linear velocity (m/s)
  M5 cmd_vel jerk RMS (lin/ang, controller 출력 + final)
  M6 min obstacle distance (m)
  M7 BT FAILURE event count
  plan publish count

신뢰도 (Reliability) :
  R1 odom Hz                — 시뮬 부하의 핵심 지표
  R2 odom Hz stability      — freeze events 빈도
  R3 cmd_vel_nav Hz         — controller 작동 정상성
  R4 sim time vs walltime   — 시뮬 시간 진행 비율
  R5 no freeze (gap > 0.1s) — 시뮬 멈춤 횟수

  종합 score:
    >= 0.85  ✅ RELIABLE
    >= 0.60  ⚠️ QUESTIONABLE
    <  0.60  ❌ UNRELIABLE
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import mean, stdev

from mcap.reader import make_reader
from mcap_ros2.decoder import DecoderFactory


# ───────────────────────── Reliability targets ─────────────────────────
# nav2_params_sim.yaml 기준 expected Hz (sanity 측정값 반영)
TARGET = {
    "odom_hz": 42.0,         # 실제 시뮬 평균 44, 여유 2
    "odom_deadline": 25.0,   # 25Hz 이하면 시뮬 부하 심각
    "cmd_vel_hz": 20.0,
    "cmd_vel_deadline": 10.0,
    "sim_rt_factor": 0.95,
    "sim_rt_deadline": 0.70,
    "freeze_threshold_s": 0.10,  # 100ms 이상 odom 끊김 = freeze 1회
    # M13 AMCL localization quality — map→odom 보정량
    # AMCL 이 odom 을 자주/크게 끌어당기면 lidar↔map 일치도 낮음
    "loc_drift_rms": 0.005,      # 5 mm/s 이하 → 만점 (conservative, 실측 후 튜닝)
    "loc_drift_deadline": 0.050, # 50 mm/s 이상 → 0점
}

WEIGHTS = {
    "odom_hz": 0.25,
    "odom_stab": 0.15,
    "cmd_vel_hz": 0.15,
    "sim_clock": 0.15,
    "no_freeze": 0.10,
    "localization": 0.20,   # M13 — 부드러움 ↔ lidar 안정성 상관
}


def score(actual: float, target: float, deadline: float) -> float:
    """target 이상이면 1.0, deadline 이하면 0.0, 사이는 linear."""
    if actual >= target:
        return 1.0
    if actual <= deadline:
        return 0.0
    return (actual - deadline) / (target - deadline)


def clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def topic_hz_stats(timestamps: list[float]) -> tuple[float, float, int]:
    """timestamps (sec) 로부터 (avg_hz, std_hz, n_freezes) 계산.

    freezes = gap > TARGET['freeze_threshold_s'] 인 인접 timestamp 의 개수.
    """
    if len(timestamps) < 2:
        return 0.0, 0.0, 0
    gaps = [timestamps[i + 1] - timestamps[i] for i in range(len(timestamps) - 1)]
    n_freezes = sum(1 for g in gaps if g > TARGET["freeze_threshold_s"])
    duration = timestamps[-1] - timestamps[0]
    avg_hz = (len(timestamps) - 1) / duration if duration > 0 else 0
    # window-based std: 1초 windows 의 Hz 의 std
    n_windows = max(1, int(duration))
    win_counts = [0] * n_windows
    for t in timestamps:
        idx = min(int(t - timestamps[0]), n_windows - 1)
        win_counts[idx] += 1
    std_hz = stdev(win_counts) if len(win_counts) > 1 else 0.0
    return avg_hz, std_hz, n_freezes


def compute_xte(
    odom_xy: list[tuple[float, float, float]],
    plans: list[tuple[float, list[tuple[float, float]]]],
    tf_map_odom: list[tuple[float, float, float, float]],
) -> dict:
    """Cross-Track Error — 각 odom 시점에서 가장 최근 plan 의 nearest point 거리.

    좌표계:
      - /gogoping/odom 의 pose 는 odom frame 기준
      - /plan 은 map frame 기준
      → /tf 의 map→gogoping/odom transform 으로 odom 위치를 map frame 으로 변환 후 비교.
    """
    if not odom_xy or not plans or not tf_map_odom:
        return {"xte_mean": 0.0, "xte_max": 0.0, "xte_p95": 0.0, "n_samples": 0}

    plan_ts = [p[0] for p in plans]
    tf_ts = [t for t, _, _, _ in tf_map_odom]
    xtes = []
    j = 0  # plan 인덱스
    k = 0  # tf 인덱스
    for t, x_o, y_o in odom_xy:
        # 시점 t 이전의 가장 최근 plan
        while j + 1 < len(plan_ts) and plan_ts[j + 1] <= t:
            j += 1
        if plan_ts[j] > t:
            continue
        # 시점 t 이전의 가장 최근 map→odom transform
        while k + 1 < len(tf_ts) and tf_ts[k + 1] <= t:
            k += 1
        if tf_ts[k] > t:
            continue
        tx, ty, yaw = tf_map_odom[k][1], tf_map_odom[k][2], tf_map_odom[k][3]
        # odom frame 좌표 → map frame
        c, s = math.cos(yaw), math.sin(yaw)
        x_m = tx + c * x_o - s * y_o
        y_m = ty + s * x_o + c * y_o
        path = plans[j][1]
        d_min = min(math.hypot(x_m - px, y_m - py) for px, py in path)
        xtes.append(d_min)

    if not xtes:
        return {"xte_mean": 0.0, "xte_max": 0.0, "xte_p95": 0.0, "n_samples": 0}
    xtes_sorted = sorted(xtes)
    p95 = xtes_sorted[int(0.95 * (len(xtes) - 1))]
    return {
        "xte_mean": sum(xtes) / len(xtes),
        "xte_max": max(xtes),
        "xte_p95": p95,
        "n_samples": len(xtes),
    }


def compute_planning_latency(
    bt_events: list[tuple[float, str, str, str]],
) -> dict:
    """ComputePathToPose / ComputePathThroughPoses 의 IDLE→RUNNING → next status 시간.

    각 node 별 latency 리스트 → mean / p95 / max.
    """
    targets = {"ComputePathToPose", "ComputePathThroughPoses"}
    starts: dict[str, float] = {}  # node 별 가장 최근 RUNNING 시작 시간
    latencies: list[float] = []
    fail_count = 0
    success_count = 0
    for t, node, prev, curr in bt_events:
        if node not in targets:
            continue
        if curr == "RUNNING" and prev == "IDLE":
            starts[node] = t
        elif prev == "RUNNING" and curr in ("SUCCESS", "FAILURE"):
            if node in starts:
                latencies.append(t - starts[node])
                del starts[node]
                if curr == "SUCCESS":
                    success_count += 1
                else:
                    fail_count += 1

    if not latencies:
        return {
            "plan_latency_mean_s": 0.0,
            "plan_latency_p95_s": 0.0,
            "plan_latency_max_s": 0.0,
            "plan_call_n": 0,
            "plan_success_n": 0,
            "plan_failure_n": 0,
        }
    lat_sorted = sorted(latencies)
    p95 = lat_sorted[int(0.95 * (len(lat_sorted) - 1))]
    return {
        "plan_latency_mean_s": sum(latencies) / len(latencies),
        "plan_latency_p95_s": p95,
        "plan_latency_max_s": max(latencies),
        "plan_call_n": len(latencies),
        "plan_success_n": success_count,
        "plan_failure_n": fail_count,
    }


def compute_recovery_breakdown(
    bt_events: list[tuple[float, str, str, str]],
) -> dict:
    """BT event 를 의미별로 분류 — M7 노이즈 청소.

    카테고리:
      planner   : ComputePathToPose / ComputePathThroughPoses
      controller: FollowPath
      recovery  : Spin / BackUp / Wait / DriveOnHeading
      (그 외 GoalUpdated 같은 operational 은 제외)
    """
    planner_nodes = {"ComputePathToPose", "ComputePathThroughPoses"}
    controller_nodes = {"FollowPath"}
    recovery_nodes = {"Spin", "BackUp", "Wait", "DriveOnHeading"}

    counts = {
        "planner_success": 0, "planner_failure": 0,
        "controller_success": 0, "controller_failure": 0,
        "recovery_spin_n": 0, "recovery_backup_n": 0,
        "recovery_wait_n": 0, "recovery_drive_n": 0,
        "recovery_total_n": 0, "recovery_failure_n": 0,
    }
    for _t, node, prev, curr in bt_events:
        if prev != "RUNNING":
            continue
        if curr not in ("SUCCESS", "FAILURE"):
            continue
        if node in planner_nodes:
            if curr == "SUCCESS":
                counts["planner_success"] += 1
            else:
                counts["planner_failure"] += 1
        elif node in controller_nodes:
            if curr == "SUCCESS":
                counts["controller_success"] += 1
            else:
                counts["controller_failure"] += 1
        elif node in recovery_nodes:
            counts["recovery_total_n"] += 1
            if curr == "FAILURE":
                counts["recovery_failure_n"] += 1
            if node == "Spin":
                counts["recovery_spin_n"] += 1
            elif node == "BackUp":
                counts["recovery_backup_n"] += 1
            elif node == "Wait":
                counts["recovery_wait_n"] += 1
            elif node == "DriveOnHeading":
                counts["recovery_drive_n"] += 1
    return counts


def compute_total_yaw(
    odom_twist: list[tuple[float, float, float]],
) -> float:
    """누적 회전량 = ∫ |ω| dt — odom 의 angular velocity 적분.

    부호 무관 — 회전 효율성 (직선 vs 빙빙) 측정.
    """
    if len(odom_twist) < 2:
        return 0.0
    total = 0.0
    for i in range(len(odom_twist) - 1):
        dt = odom_twist[i + 1][0] - odom_twist[i][0]
        if dt <= 0:
            continue
        omega = abs(odom_twist[i][2])
        total += omega * dt
    return total


def compute_amcl_drift(
    tf_map_odom: list[tuple[float, float, float, float]],
    jump_xy_thr: float = 0.05,    # 5 cm 이상 step = jump
    jump_yaw_thr: float = 0.087,  # 5° (0.087 rad) 이상 step = jump
) -> dict:
    """map→odom transform 의 시간미분 = AMCL 보정량.

    의미:
      - map→odom 은 AMCL 이 scan↔map 매칭으로 끊임없이 보정하는 상대 transform
      - 보정량이 크다 = lidar 와 map 이 잘 안 맞아서 자주/크게 끌어당김
      - 보정량이 작다 = scan match 양호 = localization 안정

    반환:
      drift_rms       : sqrt(mean(v²)) — 평균 보정 속도 [m/s 환산]
      drift_p95       : 상위 5% 보정 속도
      drift_yaw_rms   : 각속도 보정량 [rad/s]
      jump_count      : step 크기 > threshold 인 횟수 (확 튀는 보정)
    """
    if len(tf_map_odom) < 2:
        return {
            "drift_rms": 0.0, "drift_p95": 0.0,
            "drift_yaw_rms": 0.0, "jump_count": 0,
        }

    drifts_xy: list[float] = []
    drifts_yaw: list[float] = []
    jumps = 0
    for i in range(len(tf_map_odom) - 1):
        t0, x0, y0, yaw0 = tf_map_odom[i]
        t1, x1, y1, yaw1 = tf_map_odom[i + 1]
        dt = t1 - t0
        if dt <= 0:
            continue
        dxy = math.hypot(x1 - x0, y1 - y0)
        # yaw wrap
        dyaw = yaw1 - yaw0
        while dyaw > math.pi:
            dyaw -= 2 * math.pi
        while dyaw < -math.pi:
            dyaw += 2 * math.pi
        dyaw = abs(dyaw)
        drifts_xy.append(dxy / dt)
        drifts_yaw.append(dyaw / dt)
        if dxy > jump_xy_thr or dyaw > jump_yaw_thr:
            jumps += 1

    if not drifts_xy:
        return {
            "drift_rms": 0.0, "drift_p95": 0.0,
            "drift_yaw_rms": 0.0, "jump_count": 0,
        }
    rms_xy = math.sqrt(sum(d * d for d in drifts_xy) / len(drifts_xy))
    rms_yaw = math.sqrt(sum(d * d for d in drifts_yaw) / len(drifts_yaw))
    p95 = sorted(drifts_xy)[int(0.95 * (len(drifts_xy) - 1))]
    return {
        "drift_rms": rms_xy,
        "drift_p95": p95,
        "drift_yaw_rms": rms_yaw,
        "jump_count": jumps,
    }


def compute_obs_distribution(
    scan_min: list[tuple[float, float]],
) -> dict:
    """scan_min 의 분포 — p10 / p50 / mean. M6 (단일 최솟값) 확장."""
    if not scan_min:
        return {"obs_p10_m": 0.0, "obs_p50_m": 0.0, "obs_mean_m": 0.0}
    ds = sorted(d for _, d in scan_min)
    n = len(ds)
    return {
        "obs_p10_m": ds[int(0.10 * (n - 1))],
        "obs_p50_m": ds[int(0.50 * (n - 1))],
        "obs_mean_m": sum(ds) / n,
    }


def compute_stuck_events(
    odom_twist: list[tuple[float, float, float]],
    state_history: list[tuple[float, str]],
    vel_threshold: float = 0.02,
    ang_threshold: float = 0.05,
    min_duration: float = 2.0,
) -> dict:
    """|v_lin| < threshold AND |v_ang| < threshold 가 min_duration 이상 지속 → stuck 1회.

    IDLE/CHARGING 같은 비-운행 state 는 제외 (state_history 가 있을 때).
    """
    if not odom_twist:
        return {"stuck_count": 0, "stuck_total_s": 0.0, "stuck_max_s": 0.0}

    # 운행중인 state 만 고려 — GOTO/MOVING/RETURNING 류
    operational_states = {"GOTO", "MOVING", "RETURNING", "RECOVERING"}

    def is_operational(t: float) -> bool:
        if not state_history:
            return True
        # state_history 에서 t 이전 가장 최근 state 찾기
        cur = state_history[0][1]
        for st, s in state_history:
            if st > t:
                break
            cur = s
        return cur in operational_states

    stuck_intervals: list[float] = []
    in_stuck = False
    stuck_start = 0.0
    for t, vlin, vang in odom_twist:
        is_stopped = abs(vlin) < vel_threshold and abs(vang) < ang_threshold
        if is_stopped and is_operational(t):
            if not in_stuck:
                in_stuck = True
                stuck_start = t
        else:
            if in_stuck:
                duration = t - stuck_start
                if duration >= min_duration:
                    stuck_intervals.append(duration)
                in_stuck = False
    # bag 끝까지 stuck 이면
    if in_stuck:
        duration = odom_twist[-1][0] - stuck_start
        if duration >= min_duration:
            stuck_intervals.append(duration)

    return {
        "stuck_count": len(stuck_intervals),
        "stuck_total_s": sum(stuck_intervals),
        "stuck_max_s": max(stuck_intervals) if stuck_intervals else 0.0,
    }


def smoother_involvement(
    pre: list[tuple[float, float, float]],
    post: list[tuple[float, float, float]],
    active_threshold: float = 0.005,
) -> dict:
    """velocity_smoother 의 활동 지표.

    pre  = /gogoping/cmd_vel_nav   (smoother 입력 = controller 출력)
    post = /gogoping/cmd_vel_raw   (smoother 출력)

    매 post sample 에 대해 가장 가까운 pre sample 을 매칭하여 |Δv| 측정.

    반환:
      involvement_rate    : smoother 가 명령을 active_threshold 이상 바꾼 비율 (0~1)
      clip_lin_mean_act   : active 구간 평균 |Δlin|
      clip_ang_mean_act   : active 구간 평균 |Δang|
      jerk_reduction_lin  : (jerk_pre - jerk_post) / jerk_pre   양수면 smoother 가 부드럽게
      jerk_reduction_ang  : 동일 (angular)
    """
    if len(pre) < 3 or len(post) < 3:
        return {
            "involvement_rate": 0.0,
            "clip_lin_mean_act": 0.0,
            "clip_ang_mean_act": 0.0,
            "jerk_reduction_lin_pct": 0.0,
            "jerk_reduction_ang_pct": 0.0,
        }

    pre_t = [t for t, _, _ in pre]
    # 각 post 시점에 대해 가장 가까운 pre 인덱스 찾기 (양쪽 정렬 가정 → two-pointer)
    j = 0
    deltas_lin = []
    deltas_ang = []
    for t_post, v_post, w_post in post:
        while j + 1 < len(pre_t) and pre_t[j + 1] <= t_post:
            j += 1
        # j 와 j+1 중 더 가까운 쪽
        if j + 1 < len(pre_t) and abs(pre_t[j + 1] - t_post) < abs(pre_t[j] - t_post):
            k = j + 1
        else:
            k = j
        if abs(pre_t[k] - t_post) > 0.2:  # 200ms 이상 떨어지면 매칭 실패
            continue
        v_pre = pre[k][1]
        w_pre = pre[k][2]
        deltas_lin.append(abs(v_pre - v_post))
        deltas_ang.append(abs(w_pre - w_post))

    if not deltas_lin:
        return {
            "involvement_rate": 0.0,
            "clip_lin_mean_act": 0.0,
            "clip_ang_mean_act": 0.0,
            "jerk_reduction_lin_pct": 0.0,
            "jerk_reduction_ang_pct": 0.0,
        }

    active = [
        i for i, (dv, dw) in enumerate(zip(deltas_lin, deltas_ang))
        if dv > active_threshold or dw > active_threshold
    ]
    involvement_rate = len(active) / len(deltas_lin)
    clip_lin_mean_act = (
        sum(deltas_lin[i] for i in active) / len(active) if active else 0.0
    )
    clip_ang_mean_act = (
        sum(deltas_ang[i] for i in active) / len(active) if active else 0.0
    )

    def _jerk_rms(cv):
        if len(cv) < 3:
            return 0.0, 0.0
        ts = [t for t, _, _ in cv]
        lin = [v for _, v, _ in cv]
        ang = [w for _, _, w in cv]
        jl, ja = [], []
        for i in range(len(cv) - 1):
            dt = ts[i + 1] - ts[i]
            if dt <= 0:
                continue
            jl.append((lin[i + 1] - lin[i]) / dt)
            ja.append((ang[i + 1] - ang[i]) / dt)
        if not jl:
            return 0.0, 0.0
        return (
            math.sqrt(sum(d * d for d in jl) / len(jl)),
            math.sqrt(sum(d * d for d in ja) / len(ja)),
        )

    jl_pre, ja_pre = _jerk_rms(pre)
    jl_post, ja_post = _jerk_rms(post)
    jerk_red_lin = ((jl_pre - jl_post) / jl_pre * 100.0) if jl_pre > 1e-6 else 0.0
    jerk_red_ang = ((ja_pre - ja_post) / ja_pre * 100.0) if ja_pre > 1e-6 else 0.0

    return {
        "involvement_rate": involvement_rate,
        "clip_lin_mean_act": clip_lin_mean_act,
        "clip_ang_mean_act": clip_ang_mean_act,
        "jerk_reduction_lin_pct": jerk_red_lin,
        "jerk_reduction_ang_pct": jerk_red_ang,
    }


# ───────────────────────── M14: L1(레인) vs L2(실주행) 경로 유사도 ─────────────────────────
def _pt_seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _pt_polyline_dist(px, py, poly):
    if len(poly) >= 2:
        return min(
            _pt_seg_dist(px, py, poly[i][0], poly[i][1], poly[i + 1][0], poly[i + 1][1])
            for i in range(len(poly) - 1)
        )
    return min(math.hypot(px - qx, py - qy) for qx, qy in poly) if poly else float("inf")


def _downsample(poly, cap):
    if len(poly) <= cap:
        return poly
    step = len(poly) / cap
    return [poly[int(i * step)] for i in range(cap)]


def _densify(poly, step):
    """폴리라인을 step(m) 간격으로 보간 — sparse vertex 레인을 조밀한 점열로.

    discrete Fréchet 은 점-대-점 짝짓기라, route_path 처럼 vertex 만 있는 sparse
    폴리라인엔 중간 점이 없어 값이 부풀려진다 → 보간으로 L2 와 밀도 맞춤.
    """
    if len(poly) < 2:
        return poly
    out = [poly[0]]
    for i in range(len(poly) - 1):
        ax, ay = poly[i]
        bx, by = poly[i + 1]
        seg = math.hypot(bx - ax, by - ay)
        n = max(1, int(seg / step))
        for k in range(1, n + 1):
            t = k / n
            out.append((ax + t * (bx - ax), ay + t * (by - ay)))
    return out


def _discrete_frechet(P, Q):
    """discrete Fréchet distance (반복 DP, O(n·m))."""
    n, m = len(P), len(Q)
    if n == 0 or m == 0:
        return 0.0
    ca = [[0.0] * m for _ in range(n)]
    for i in range(n):
        for j in range(m):
            dij = math.hypot(P[i][0] - Q[j][0], P[i][1] - Q[j][1])
            if i == 0 and j == 0:
                ca[i][j] = dij
            elif i == 0:
                ca[i][j] = max(ca[0][j - 1], dij)
            elif j == 0:
                ca[i][j] = max(ca[i - 1][0], dij)
            else:
                ca[i][j] = max(min(ca[i - 1][j], ca[i - 1][j - 1], ca[i][j - 1]), dij)
    return ca[n - 1][m - 1]


def compute_lane_similarity(
    route_paths: list[tuple[float, list[tuple[float, float]]]],
    odom_xy: list[tuple[float, float, float]],
    tf_map_odom: list[tuple[float, float, float, float]],
) -> dict:
    """M14 — L1(graph_router route_path = 레인 경로) vs L2(실주행 odom, map frame) 유사도.

    L1 = route_path pose 들을 순서대로 이은 폴리라인 (vertex 직선 레인).
    L2 = odom 을 map frame 으로 변환한 실제 궤적.
    → 실주행이 의도한 레인에서 얼마나 벗어났나 (planner 가 레인 충실 vs 코너컷·우회).
    """
    empty = {
        "lane_dev_mean_m": 0.0, "lane_dev_p95_m": 0.0, "lane_dev_max_m": 0.0,
        "lane_frechet_m": 0.0, "lane_n_samples": 0,
    }
    l1: list[tuple[float, float]] = []
    for _t, poly in route_paths:
        for x, y in poly:
            if not l1 or math.hypot(x - l1[-1][0], y - l1[-1][1]) > 1e-3:
                l1.append((x, y))
    if len(l1) < 2 or not odom_xy or not tf_map_odom:
        return empty
    tf_ts = [t for t, _, _, _ in tf_map_odom]
    l2: list[tuple[float, float]] = []
    k = 0
    for t, x_o, y_o in odom_xy:
        while k + 1 < len(tf_ts) and tf_ts[k + 1] <= t:
            k += 1
        if tf_ts[k] > t:
            continue
        _, tx, ty, yaw = tf_map_odom[k]
        c, s = math.cos(yaw), math.sin(yaw)
        l2.append((tx + c * x_o - s * y_o, ty + s * x_o + c * y_o))
    if len(l2) < 2:
        return empty
    devs = sorted(_pt_polyline_dist(px, py, l1) for px, py in l2)
    n = len(devs)
    # frechet: L1 을 0.1m 간격 보간(densify) 후 비교 — sparse vertex 부풀림 방지.
    frechet = _discrete_frechet(_downsample(_densify(l1, 0.1), 300), _downsample(l2, 300))
    return {
        "lane_dev_mean_m": sum(devs) / n,
        "lane_dev_p95_m": devs[int(0.95 * (n - 1))],
        "lane_dev_max_m": devs[-1],
        "lane_frechet_m": frechet,
        "lane_n_samples": n,
    }


# ───────────────────────── M15: costmap 민감도 ─────────────────────────
def _sample_costmap(cm, x: float, y: float):
    """local costmap (odom frame) 의 (x,y) cost. 범위 밖/unknown(-1) 이면 None."""
    w, h, res, ox, oy, data = cm
    if res <= 0:
        return None
    col = int((x - ox) / res)
    row = int((y - oy) / res)
    if 0 <= col < w and 0 <= row < h:
        v = data[row * w + col]
        if v >= 0:
            return float(v)
    return None


def compute_vel_clearance_corr(
    odom_twist: list[tuple[float, float, float]],
    scan_min: list[tuple[float, float]],
) -> float:
    """corr(|v_lin|, scan_min) — 장애물 가까울수록 감속하면 양수 (costmap 반응성)."""
    if len(odom_twist) < 3 or len(scan_min) < 3:
        return 0.0
    sm_ts = [t for t, _ in scan_min]
    xs, ys = [], []
    k = 0
    for t, vlin, _ in odom_twist:
        while k + 1 < len(sm_ts) and sm_ts[k + 1] <= t:
            k += 1
        if abs(sm_ts[k] - t) > 0.5:
            continue
        xs.append(abs(vlin))
        ys.append(scan_min[k][1])
    if len(xs) < 3:
        return 0.0
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def analyze_bag(bag_path: Path) -> dict:
    odom_xy: list[tuple[float, float, float]] = []
    odom_twist: list[tuple[float, float, float]] = []  # (t, lin_x, ang_z)
    odom_stamps: list[float] = []
    cmd_vel_nav: list[tuple[float, float, float]] = []
    cmd_nav_stamps: list[float] = []
    cmd_vel_raw: list[tuple[float, float, float]] = []  # smoother 출력
    cmd_raw_stamps: list[float] = []
    cmd_vel_final: list[tuple[float, float, float]] = []
    cmd_final_stamps: list[float] = []
    scan_min: list[tuple[float, float]] = []
    scan_stamps: list[float] = []
    # plan: 시점별 (t, [(x, y), ...]) — XTE 계산용
    plans: list[tuple[float, list[tuple[float, float]]]] = []
    # BT events: planning latency, recovery breakdown 용
    bt_events: list[tuple[float, str, str, str]] = []  # (t, node, prev, curr)
    # TF: map → gogoping/odom transform (XTE 의 좌표계 변환용)
    tf_map_odom: list[tuple[float, float, float, float]] = []  # (t, tx, ty, yaw)
    route_paths: list[tuple[float, list[tuple[float, float]]]] = []  # M14 — L1 레인 경로
    latest_costmap = None  # M15 — (w, h, res, ox, oy, data) 최신 local costmap
    cost_series: list[float] = []  # M15 — 로봇 위치의 costmap cost 시계열
    plan_pubs = 0
    bt_failures = 0
    state_history: list[tuple[float, str]] = []
    prev_state: str | None = None

    # sim time vs walltime
    first_log_time: float | None = None
    last_log_time: float | None = None
    first_odom_stamp: float | None = None
    last_odom_stamp: float | None = None

    with bag_path.open("rb") as f:
        reader = make_reader(f, decoder_factories=[DecoderFactory()])
        for schema, channel, msg, ros_msg in reader.iter_decoded_messages():
            topic = channel.topic
            log_t = msg.log_time / 1e9
            if first_log_time is None:
                first_log_time = log_t
            last_log_time = log_t

            if topic == "/gogoping/odom":
                p = ros_msg.pose.pose.position
                odom_xy.append((log_t, p.x, p.y))
                if latest_costmap is not None:   # M15 — 로봇 위치 costmap cost 샘플
                    _cv = _sample_costmap(latest_costmap, p.x, p.y)
                    if _cv is not None:
                        cost_series.append(_cv)
                tw = ros_msg.twist.twist
                odom_twist.append((log_t, tw.linear.x, tw.angular.z))
                odom_stamps.append(log_t)
                stamp = ros_msg.header.stamp.sec + ros_msg.header.stamp.nanosec / 1e9
                if first_odom_stamp is None:
                    first_odom_stamp = stamp
                last_odom_stamp = stamp
            elif topic == "/gogoping/cmd_vel_nav":
                cmd_vel_nav.append((log_t, ros_msg.linear.x, ros_msg.angular.z))
                cmd_nav_stamps.append(log_t)
            elif topic == "/gogoping/cmd_vel_raw":
                cmd_vel_raw.append((log_t, ros_msg.linear.x, ros_msg.angular.z))
                cmd_raw_stamps.append(log_t)
            elif topic == "/gogoping/cmd_vel":
                cmd_vel_final.append((log_t, ros_msg.linear.x, ros_msg.angular.z))
                cmd_final_stamps.append(log_t)
            elif topic == "/gogoping/scan_filtered":
                rs = [
                    r for r in ros_msg.ranges
                    if 0.1 < r < 100 and not math.isnan(r) and not math.isinf(r)
                ]
                if rs:
                    scan_min.append((log_t, min(rs)))
                    scan_stamps.append(log_t)
            elif topic == "/tf":
                for tr in ros_msg.transforms:
                    if (
                        tr.header.frame_id == "map"
                        and tr.child_frame_id == "gogoping/odom"
                    ):
                        q = tr.transform.rotation
                        yaw = math.atan2(
                            2.0 * (q.w * q.z + q.x * q.y),
                            1.0 - 2.0 * (q.y * q.y + q.z * q.z),
                        )
                        tf_map_odom.append((
                            log_t,
                            tr.transform.translation.x,
                            tr.transform.translation.y,
                            yaw,
                        ))
            elif topic == "/plan":
                plan_pubs += 1
                poses_xy = [(p.pose.position.x, p.pose.position.y) for p in ros_msg.poses]
                if poses_xy:
                    plans.append((log_t, poses_xy))
            elif topic == "/graph_router/route_path":   # M14 — L1 레인 경로
                route_paths.append(
                    (log_t, [(ps.pose.position.x, ps.pose.position.y) for ps in ros_msg.poses])
                )
            elif topic == "/local_costmap/costmap":   # M15 — costmap 민감도
                _info = ros_msg.info
                latest_costmap = (
                    _info.width, _info.height, _info.resolution,
                    _info.origin.position.x, _info.origin.position.y,
                    ros_msg.data,
                )
            elif topic == "/behavior_tree_log":
                for ev in ros_msg.event_log:
                    ev_t = ev.timestamp.sec + ev.timestamp.nanosec / 1e9
                    bt_events.append((ev_t, ev.node_name, ev.previous_status, ev.current_status))
                    if ev.current_status == "FAILURE":
                        bt_failures += 1
            elif topic == "/gogoping/state_str":
                if ros_msg.data != prev_state:
                    state_history.append((log_t, ros_msg.data))
                    prev_state = ros_msg.data

    # ───────────── Metrics ─────────────
    duration = odom_xy[-1][0] - odom_xy[0][0] if odom_xy else 0

    path_len = sum(
        math.hypot(
            odom_xy[i][1] - odom_xy[i - 1][1],
            odom_xy[i][2] - odom_xy[i - 1][2],
        )
        for i in range(1, len(odom_xy))
    )

    vels = [abs(v) for _, v, _ in cmd_vel_nav]
    avg_vel = mean(vels) if vels else 0
    max_vel = max(vels) if vels else 0

    def jerk_stats(cv):
        """time-aware jerk RMS — dt 로 나눠서 단위 (1/s²) 통일."""
        if len(cv) < 3:
            return 0.0, 0.0
        ts = [t for t, _, _ in cv]
        lin = [v for _, v, _ in cv]
        ang = [w for _, _, w in cv]
        jlin = []
        jang = []
        for i in range(len(cv) - 1):
            dt = ts[i + 1] - ts[i]
            if dt <= 0:
                continue
            jlin.append((lin[i + 1] - lin[i]) / dt)
            jang.append((ang[i + 1] - ang[i]) / dt)
        if not jlin:
            return 0.0, 0.0
        lin_rms = math.sqrt(sum(d * d for d in jlin) / len(jlin))
        ang_rms = math.sqrt(sum(d * d for d in jang) / len(jang))
        return lin_rms, ang_rms

    nav_lin_jerk, nav_ang_jerk = jerk_stats(cmd_vel_nav)
    raw_lin_jerk, raw_ang_jerk = jerk_stats(cmd_vel_raw)
    odom_lin_jerk, odom_ang_jerk = jerk_stats(odom_twist)
    final_lin_jerk, final_ang_jerk = jerk_stats(cmd_vel_final)

    # ───────────── Smoother involvement ─────────────
    smoother = smoother_involvement(cmd_vel_nav, cmd_vel_raw)

    # ───────────── XTE / Planning latency / Stuck (Step B) ─────────────
    xte = compute_xte(odom_xy, plans, tf_map_odom)
    plat = compute_planning_latency(bt_events)
    stuck = compute_stuck_events(odom_twist, state_history)

    # ───────────── Recovery breakdown / Total yaw / Obs dist (Step C) ─────────────
    rec = compute_recovery_breakdown(bt_events)
    total_yaw = compute_total_yaw(odom_twist)
    obs_dist = compute_obs_distribution(scan_min)

    # ───────────── AMCL drift (Step D) ─────────────
    amcl = compute_amcl_drift(tf_map_odom)

    # ───────────── M14 lane similarity / M15 costmap sensitivity ─────────────
    lane = compute_lane_similarity(route_paths, odom_xy, tf_map_odom)
    vel_corr = compute_vel_clearance_corr(odom_twist, scan_min)
    if cost_series:
        _cs = sorted(cost_series)
        _ncs = len(_cs)
        cost_mean = sum(_cs) / _ncs
        cost_p95 = _cs[int(0.95 * (_ncs - 1))]
        cost_max = _cs[-1]
        high_cost_ratio = sum(1 for v in _cs if v >= 50) / _ncs
    else:
        cost_mean = cost_p95 = cost_max = high_cost_ratio = 0.0

    obs_min = min(d for _, d in scan_min) if scan_min else 0

    # ───────────── Reliability ─────────────
    odom_hz, odom_std, odom_freezes = topic_hz_stats(odom_stamps)
    cmd_nav_hz, _, _ = topic_hz_stats(cmd_nav_stamps)
    scan_hz, _, _ = topic_hz_stats(scan_stamps)

    sim_dt = (
        (last_odom_stamp - first_odom_stamp)
        if first_odom_stamp is not None and last_odom_stamp is not None
        else 0
    )
    wall_dt = (last_log_time - first_log_time) if first_log_time else 0
    sim_rt_factor = sim_dt / wall_dt if wall_dt > 0 else 0

    odom_hz_score = score(odom_hz, TARGET["odom_hz"], TARGET["odom_deadline"])
    odom_stab_score = 1 - clip(odom_std / 5.0, 0, 1)
    cmd_vel_score = score(cmd_nav_hz, TARGET["cmd_vel_hz"], TARGET["cmd_vel_deadline"])
    sim_clock_score = score(sim_rt_factor, TARGET["sim_rt_factor"], TARGET["sim_rt_deadline"])
    no_freeze_score = 1 - clip(odom_freezes / 50.0, 0, 1)
    # M13 — drift 작을수록 점수 ↑ (score() 시그니처가 큰 actual=좋음 가정이라 부호 반전)
    loc_score = score(
        -amcl["drift_rms"],
        -TARGET["loc_drift_rms"],
        -TARGET["loc_drift_deadline"],
    )

    reliability = (
        WEIGHTS["odom_hz"] * odom_hz_score
        + WEIGHTS["odom_stab"] * odom_stab_score
        + WEIGHTS["cmd_vel_hz"] * cmd_vel_score
        + WEIGHTS["sim_clock"] * sim_clock_score
        + WEIGHTS["no_freeze"] * no_freeze_score
        + WEIGHTS["localization"] * loc_score
    )

    if reliability >= 0.85:
        grade = "RELIABLE"
    elif reliability >= 0.60:
        grade = "QUESTIONABLE"
    else:
        grade = "UNRELIABLE"

    return {
        "bag": str(bag_path),
        "metrics": {
            "M2_duration_s": duration,
            "M3_path_len_m": path_len,
            "M4_avg_vel_mps": avg_vel,
            "M4_max_vel_mps": max_vel,
            # Stage 별 jerk RMS (단위 m/s² · rad/s²)
            "M5_nav_lin_jerk_rms": nav_lin_jerk,       # controller 출력
            "M5_nav_ang_jerk_rms": nav_ang_jerk,
            "M5_raw_lin_jerk_rms": raw_lin_jerk,       # smoother 출력
            "M5_raw_ang_jerk_rms": raw_ang_jerk,
            "M5_odom_lin_jerk_rms": odom_lin_jerk,     # 실제 주행
            "M5_odom_ang_jerk_rms": odom_ang_jerk,
            "M5_final_lin_jerk_rms": final_lin_jerk,   # legacy (cmd_vel = relay)
            "M5_final_ang_jerk_rms": final_ang_jerk,
            # Smoother 관여
            "M5s_involvement_rate": smoother["involvement_rate"],
            "M5s_clip_lin_mean_act": smoother["clip_lin_mean_act"],
            "M5s_clip_ang_mean_act": smoother["clip_ang_mean_act"],
            "M5s_jerk_reduction_lin_pct": smoother["jerk_reduction_lin_pct"],
            "M5s_jerk_reduction_ang_pct": smoother["jerk_reduction_ang_pct"],
            # Step B — XTE (controller path-following)
            "M8_xte_mean_m": xte["xte_mean"],
            "M8_xte_p95_m": xte["xte_p95"],
            "M8_xte_max_m": xte["xte_max"],
            # Step B — Planning latency (planner)
            "M9_plan_latency_mean_s": plat["plan_latency_mean_s"],
            "M9_plan_latency_p95_s": plat["plan_latency_p95_s"],
            "M9_plan_latency_max_s": plat["plan_latency_max_s"],
            "M9_plan_call_n": plat["plan_call_n"],
            "M9_plan_success_n": plat["plan_success_n"],
            "M9_plan_failure_n": plat["plan_failure_n"],
            # Step B — Stuck events (system)
            "M10_stuck_count": stuck["stuck_count"],
            "M10_stuck_total_s": stuck["stuck_total_s"],
            "M10_stuck_max_s": stuck["stuck_max_s"],
            # Step C — Recovery breakdown (BT 실패 분류)
            "M11_planner_success_n": rec["planner_success"],
            "M11_planner_failure_n": rec["planner_failure"],
            "M11_controller_success_n": rec["controller_success"],
            "M11_controller_failure_n": rec["controller_failure"],
            "M11_recovery_total_n": rec["recovery_total_n"],
            "M11_recovery_spin_n": rec["recovery_spin_n"],
            "M11_recovery_backup_n": rec["recovery_backup_n"],
            "M11_recovery_wait_n": rec["recovery_wait_n"],
            "M11_recovery_drive_n": rec["recovery_drive_n"],
            "M11_recovery_failure_n": rec["recovery_failure_n"],
            # Step C — Total yaw rotation (효율성)
            "M12_total_yaw_rad": total_yaw,
            # Step C — Obstacle distance distribution (M6 확장)
            "M6_obs_min_m": obs_min,
            "M6_obs_p10_m": obs_dist["obs_p10_m"],
            "M6_obs_p50_m": obs_dist["obs_p50_m"],
            "M6_obs_mean_m": obs_dist["obs_mean_m"],
            "M7_bt_failure_n": bt_failures,
            "plan_pubs": plan_pubs,
            # Step D — AMCL drift (map→odom 보정량 = localization quality)
            "M13_amcl_drift_rms": amcl["drift_rms"],
            "M13_amcl_drift_p95": amcl["drift_p95"],
            "M13_amcl_drift_yaw_rms": amcl["drift_yaw_rms"],
            "M13_amcl_jump_count": amcl["jump_count"],
            # M14 — L1(레인 route_path) vs L2(실주행) 경로 유사도
            "M14_lane_dev_mean_m": lane["lane_dev_mean_m"],
            "M14_lane_dev_p95_m": lane["lane_dev_p95_m"],
            "M14_lane_dev_max_m": lane["lane_dev_max_m"],
            "M14_lane_frechet_m": lane["lane_frechet_m"],
            "M14_lane_n": lane["lane_n_samples"],
            # M15 — costmap 민감도 (낮은 cost = 민감/회피, vel_corr 양수 = 근접 시 감속)
            "M15_cost_at_robot_mean": cost_mean,
            "M15_cost_at_robot_p95": cost_p95,
            "M15_cost_at_robot_max": cost_max,
            "M15_high_cost_ratio": high_cost_ratio,
            "M15_vel_clearance_corr": vel_corr,
        },
        "reliability": {
            "score": reliability,
            "grade": grade,
            "subscores": {
                "odom_hz": odom_hz_score,
                "odom_stab": odom_stab_score,
                "cmd_vel_hz": cmd_vel_score,
                "sim_clock": sim_clock_score,
                "no_freeze": no_freeze_score,
                "localization": loc_score,
            },
            "raw": {
                "odom_hz": odom_hz,
                "odom_std": odom_std,
                "odom_freezes": odom_freezes,
                "cmd_nav_hz": cmd_nav_hz,
                "scan_hz": scan_hz,
                "sim_rt_factor": sim_rt_factor,
                "amcl_drift_rms": amcl["drift_rms"],
                "amcl_drift_yaw_rms": amcl["drift_yaw_rms"],
                "amcl_jump_count": amcl["jump_count"],
            },
        },
        "state_history": state_history,
        "samples": {
            "odom_n": len(odom_xy),
            "cmd_nav_n": len(cmd_vel_nav),
            "cmd_raw_n": len(cmd_vel_raw),
            "cmd_final_n": len(cmd_vel_final),
            "scan_n": len(scan_min),
        },
    }


def print_summary(results: list[dict]) -> None:
    if not results:
        return
    print()
    print(f"{'metric':<25}", end="")
    for r in results:
        name = Path(r["bag"]).parents[1].name
        print(f"{name:>18}", end="")
    print()
    print("─" * (25 + 18 * len(results)))

    metric_rows = [
        ("M2 duration (s)", "M2_duration_s", "{:.1f}"),
        ("M3 path len (m)", "M3_path_len_m", "{:.2f}"),
        ("M4 avg vel (m/s)", "M4_avg_vel_mps", "{:.3f}"),
        ("M4 max vel (m/s)", "M4_max_vel_mps", "{:.3f}"),
        # Stage 별 jerk
        ("M5 jerk lin nav", "M5_nav_lin_jerk_rms", "{:.4f}"),
        ("M5 jerk lin raw", "M5_raw_lin_jerk_rms", "{:.4f}"),
        ("M5 jerk lin odom", "M5_odom_lin_jerk_rms", "{:.4f}"),
        ("M5 jerk ang nav", "M5_nav_ang_jerk_rms", "{:.4f}"),
        ("M5 jerk ang raw", "M5_raw_ang_jerk_rms", "{:.4f}"),
        ("M5 jerk ang odom", "M5_odom_ang_jerk_rms", "{:.4f}"),
        # Smoother 관여
        ("M5s involvement", "M5s_involvement_rate", "{:.2%}"),
        ("M5s clip lin (act)", "M5s_clip_lin_mean_act", "{:.4f}"),
        ("M5s clip ang (act)", "M5s_clip_ang_mean_act", "{:.4f}"),
        ("M5s jerk red lin %", "M5s_jerk_reduction_lin_pct", "{:+.1f}"),
        ("M5s jerk red ang %", "M5s_jerk_reduction_ang_pct", "{:+.1f}"),
        # Step B
        ("M8 XTE mean (m)", "M8_xte_mean_m", "{:.3f}"),
        ("M8 XTE p95 (m)", "M8_xte_p95_m", "{:.3f}"),
        ("M8 XTE max (m)", "M8_xte_max_m", "{:.3f}"),
        ("M9 plan lat mean (s)", "M9_plan_latency_mean_s", "{:.3f}"),
        ("M9 plan lat p95 (s)", "M9_plan_latency_p95_s", "{:.3f}"),
        ("M9 plan calls (#)", "M9_plan_call_n", "{:d}"),
        ("M9 plan fail (#)", "M9_plan_failure_n", "{:d}"),
        ("M10 stuck count (#)", "M10_stuck_count", "{:d}"),
        ("M10 stuck total (s)", "M10_stuck_total_s", "{:.1f}"),
        # Step C — Recovery breakdown
        ("M11 plan fail (#)", "M11_planner_failure_n", "{:d}"),
        ("M11 ctrl fail (#)", "M11_controller_failure_n", "{:d}"),
        ("M11 recovery (#)", "M11_recovery_total_n", "{:d}"),
        ("M11   spin (#)", "M11_recovery_spin_n", "{:d}"),
        ("M11   backup (#)", "M11_recovery_backup_n", "{:d}"),
        ("M11   wait (#)", "M11_recovery_wait_n", "{:d}"),
        ("M11 rec fail (#)", "M11_recovery_failure_n", "{:d}"),
        ("M12 total yaw (rad)", "M12_total_yaw_rad", "{:.2f}"),
        ("M6 obs_min (m)", "M6_obs_min_m", "{:.3f}"),
        ("M6 obs_p10 (m)", "M6_obs_p10_m", "{:.3f}"),
        ("M6 obs_p50 (m)", "M6_obs_p50_m", "{:.3f}"),
        ("M6 obs_mean (m)", "M6_obs_mean_m", "{:.3f}"),
        ("M7 BT FAILURE (#)", "M7_bt_failure_n", "{:d}"),
        ("plan pubs (#)", "plan_pubs", "{:d}"),
        # Step D — AMCL drift
        ("M13 drift rms (m/s)", "M13_amcl_drift_rms", "{:.4f}"),
        ("M13 drift p95 (m/s)", "M13_amcl_drift_p95", "{:.4f}"),
        ("M13 yaw drift rms", "M13_amcl_drift_yaw_rms", "{:.4f}"),
        ("M13 jump count (#)", "M13_amcl_jump_count", "{:d}"),
        # M14 — L1(레인) vs L2(실주행)
        ("M14 lane dev mean(m)", "M14_lane_dev_mean_m", "{:.3f}"),
        ("M14 lane dev p95 (m)", "M14_lane_dev_p95_m", "{:.3f}"),
        ("M14 lane dev max (m)", "M14_lane_dev_max_m", "{:.3f}"),
        ("M14 lane frechet (m)", "M14_lane_frechet_m", "{:.3f}"),
        # M15 — costmap 민감도
        ("M15 cost mean", "M15_cost_at_robot_mean", "{:.1f}"),
        ("M15 cost p95", "M15_cost_at_robot_p95", "{:.1f}"),
        ("M15 high-cost ratio", "M15_high_cost_ratio", "{:.2%}"),
        ("M15 vel-clr corr", "M15_vel_clearance_corr", "{:+.3f}"),
    ]
    for label, key, fmt in metric_rows:
        print(f"{label:<25}", end="")
        for r in results:
            v = r["metrics"][key]
            print(f"{fmt.format(v):>18}", end="")
        print()

    print()
    print(f"{'reliability':<25}", end="")
    for r in results:
        rel = r["reliability"]
        marker = (
            "✅" if rel["grade"] == "RELIABLE"
            else "⚠️" if rel["grade"] == "QUESTIONABLE"
            else "❌"
        )
        s = f"{marker} {rel['score']:.2f}"
        print(f"{s:>18}", end="")
    print()
    sub_rows = [
        ("  odom Hz", "odom_hz"),
        ("  odom stability", "odom_stab"),
        ("  cmd_vel Hz", "cmd_vel_hz"),
        ("  sim clock", "sim_clock"),
        ("  no freeze", "no_freeze"),
        ("  localization", "localization"),
    ]
    for label, key in sub_rows:
        print(f"{label:<25}", end="")
        for r in results:
            v = r["reliability"]["subscores"][key]
            print(f"{v:>18.2f}", end="")
        print()
    print()
    print(f"{'raw indicators':<25}")
    raw_rows = [
        ("  odom Hz (raw)", "odom_hz", "{:.1f}"),
        ("  odom std (raw)", "odom_std", "{:.2f}"),
        ("  odom freezes", "odom_freezes", "{:d}"),
        ("  cmd_nav Hz (raw)", "cmd_nav_hz", "{:.1f}"),
        ("  scan Hz (raw)", "scan_hz", "{:.1f}"),
        ("  sim_rt_factor", "sim_rt_factor", "{:.3f}"),
        ("  amcl drift (m/s)", "amcl_drift_rms", "{:.4f}"),
        ("  amcl yaw drift", "amcl_drift_yaw_rms", "{:.4f}"),
        ("  amcl jump (#)", "amcl_jump_count", "{:d}"),
    ]
    for label, key, fmt in raw_rows:
        print(f"{label:<25}", end="")
        for r in results:
            v = r["reliability"]["raw"][key]
            print(f"{fmt.format(v):>18}", end="")
        print()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bags", nargs="+", type=Path, help=".mcap files")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args()

    results = []
    for bag in args.bags:
        if not bag.exists():
            print(f"❌ not found: {bag}", file=sys.stderr)
            continue
        try:
            results.append(analyze_bag(bag))
        except Exception as e:
            print(f"❌ {bag}: {e}", file=sys.stderr)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_summary(results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
