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
}

WEIGHTS = {
    "odom_hz": 0.35,
    "odom_stab": 0.20,
    "cmd_vel_hz": 0.20,
    "sim_clock": 0.15,
    "no_freeze": 0.10,
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


def analyze_bag(bag_path: Path) -> dict:
    odom_xy: list[tuple[float, float, float]] = []
    odom_stamps: list[float] = []
    cmd_vel_nav: list[tuple[float, float, float]] = []
    cmd_nav_stamps: list[float] = []
    cmd_vel_final: list[tuple[float, float, float]] = []
    cmd_final_stamps: list[float] = []
    scan_min: list[tuple[float, float]] = []
    scan_stamps: list[float] = []
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
                odom_stamps.append(log_t)
                stamp = ros_msg.header.stamp.sec + ros_msg.header.stamp.nanosec / 1e9
                if first_odom_stamp is None:
                    first_odom_stamp = stamp
                last_odom_stamp = stamp
            elif topic == "/gogoping/cmd_vel_nav":
                cmd_vel_nav.append((log_t, ros_msg.linear.x, ros_msg.angular.z))
                cmd_nav_stamps.append(log_t)
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
            elif topic == "/plan":
                plan_pubs += 1
            elif topic == "/behavior_tree_log":
                for ev in ros_msg.event_log:
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
        if len(cv) < 3:
            return 0.0, 0.0
        lin = [v for _, v, _ in cv]
        ang = [w for _, _, w in cv]
        dlin = [lin[i + 1] - lin[i] for i in range(len(lin) - 1)]
        dang = [ang[i + 1] - ang[i] for i in range(len(ang) - 1)]
        lin_rms = math.sqrt(sum(d * d for d in dlin) / len(dlin))
        ang_rms = math.sqrt(sum(d * d for d in dang) / len(dang))
        return lin_rms, ang_rms

    nav_lin_jerk, nav_ang_jerk = jerk_stats(cmd_vel_nav)
    final_lin_jerk, final_ang_jerk = jerk_stats(cmd_vel_final)
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

    reliability = (
        WEIGHTS["odom_hz"] * odom_hz_score
        + WEIGHTS["odom_stab"] * odom_stab_score
        + WEIGHTS["cmd_vel_hz"] * cmd_vel_score
        + WEIGHTS["sim_clock"] * sim_clock_score
        + WEIGHTS["no_freeze"] * no_freeze_score
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
            "M5_nav_lin_jerk_rms": nav_lin_jerk,
            "M5_nav_ang_jerk_rms": nav_ang_jerk,
            "M5_final_lin_jerk_rms": final_lin_jerk,
            "M5_final_ang_jerk_rms": final_ang_jerk,
            "M6_obs_min_m": obs_min,
            "M7_bt_failure_n": bt_failures,
            "plan_pubs": plan_pubs,
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
            },
            "raw": {
                "odom_hz": odom_hz,
                "odom_std": odom_std,
                "odom_freezes": odom_freezes,
                "cmd_nav_hz": cmd_nav_hz,
                "scan_hz": scan_hz,
                "sim_rt_factor": sim_rt_factor,
            },
        },
        "state_history": state_history,
        "samples": {
            "odom_n": len(odom_xy),
            "cmd_nav_n": len(cmd_vel_nav),
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
        ("M5 nav ang jerk", "M5_nav_ang_jerk_rms", "{:.4f}"),
        ("M5 final ang jerk", "M5_final_ang_jerk_rms", "{:.4f}"),
        ("M5 final lin jerk", "M5_final_lin_jerk_rms", "{:.4f}"),
        ("M6 obs_min (m)", "M6_obs_min_m", "{:.3f}"),
        ("M7 BT FAILURE (#)", "M7_bt_failure_n", "{:d}"),
        ("plan pubs (#)", "plan_pubs", "{:d}"),
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
