#!/usr/bin/env python3
"""여러 run 의 bag 을 한 번에 비교 — 매트릭스 표.

사용:
  python3 compare_runs.py /tmp/runs/dense
  python3 compare_runs.py /tmp/runs/sparse
  python3 compare_runs.py /tmp/runs/dense --csv > matrix.csv
  python3 compare_runs.py /tmp/runs/dense --json > matrix.json

입력:
  <runs_dir>/<run_id>/bag/bag_0.mcap 패턴의 디렉토리.

출력:
  표 형식 (default) 또는 CSV / JSON.
  ─ run_id, P, C, rep, completed, reliability_grade, score
  ─ M2 duration, M3 path_len, M5 final_ang_jerk, M6 obs_min, M7 BT FAILURE
  ─ aggregate (mean ± std) per (P, C)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from statistics import mean, stdev

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_metrics import analyze_bag  # noqa


# run_id 패턴 : {Planner}_{Controller}_rep{N}  e.g., "NavFn_DWB_rep1"
RUN_ID_RE = re.compile(r"^([A-Za-z0-9]+)_([A-Za-z0-9]+)_rep(\d+)$")


def parse_run_id(run_id: str) -> tuple[str, str, int] | None:
    m = RUN_ID_RE.match(run_id)
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


def find_bags(runs_dir: Path) -> list[tuple[str, Path]]:
    bags = []
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        bag_dir = run_dir / "bag"
        if not bag_dir.is_dir():
            continue
        mcaps = list(bag_dir.glob("*.mcap"))
        if not mcaps:
            continue
        bags.append((run_dir.name, mcaps[0]))
    return bags


def analyze_all(runs_dir: Path) -> list[dict]:
    results = []
    for run_id, bag_path in find_bags(runs_dir):
        try:
            res = analyze_bag(bag_path)
            parsed = parse_run_id(run_id)
            if parsed:
                res["planner"], res["controller"], res["rep"] = parsed
            else:
                res["planner"], res["controller"], res["rep"] = "?", "?", 0
            res["run_id"] = run_id
            results.append(res)
        except Exception as e:
            print(f"❌ {run_id}: {e}", file=sys.stderr)
    return results


def is_completed(state_history: list) -> bool:
    """GOTO → RETURNING → IDLE/CHARGING 사이클을 끝까지 마쳤나.

    state_history 가 RETURNING 이후 IDLE/CHARGING 으로 진입했으면 완주.
    중간에 timeout 되면 RETURNING 만 보이고 그 뒤 IDLE 없음.
    """
    if not state_history:
        return False
    states = [s for _, s in state_history]
    seen_returning = False
    for s in states:
        if s == "RETURNING":
            seen_returning = True
        elif seen_returning and s in ("IDLE", "CHARGING"):
            return True
    return False


def classify_failure(r: dict) -> str:
    """실패 run 분류 — 어떤 상황에서 timeout 났나."""
    m = r["metrics"]
    if m["M11_recovery_total_n"] > 10:
        return "recovery_storm"          # 회복 행동 폭주
    if m["M6_obs_min_m"] < 0.25:
        return "near_obstacle_stuck"     # 장애물 근접 stuck
    if m["M3_path_len_m"] < 1.0:
        return "no_progress"             # 거의 못 움직임
    if m["M10_stuck_count"] > 3:
        return "frequent_stuck"          # 자주 멈춤
    if m["M11_planner_failure_n"] > 5:
        return "planning_failure"        # planner 실패 반복
    return "timeout_unknown"             # 기타


def aggregate(results: list[dict], completed_only: bool = False) -> dict:
    """같은 (planner, controller) 의 rep 들을 mean ± std 로 집계.

    completed_only=True 면 is_completed 인 rep 만 사용.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in results:
        if completed_only and not is_completed(r.get("state_history", [])):
            continue
        key = (r["planner"], r["controller"])
        groups.setdefault(key, []).append(r)

    aggregated = {}
    for (p, c), runs in groups.items():
        if not runs:
            continue
        metric_keys = list(runs[0]["metrics"].keys())
        agg = {"planner": p, "controller": c, "n": len(runs)}
        for k in metric_keys:
            vals = [r["metrics"][k] for r in runs]
            agg[k] = {
                "mean": mean(vals),
                "std": stdev(vals) if len(vals) > 1 else 0.0,
            }
        rel_scores = [r["reliability"]["score"] for r in runs]
        agg["reliability_mean"] = mean(rel_scores)
        agg["completed_n"] = sum(
            1 for r in runs if is_completed(r.get("state_history", []))
        )
        aggregated[(p, c)] = agg
    return aggregated


def print_failure_report(results: list[dict]) -> None:
    """완주 못 한 run 들의 forensics 보고서."""
    failed = [r for r in results if not is_completed(r.get("state_history", []))]
    if not failed:
        print()
        print("✅ 모든 run 완주 — 실패 보고 없음")
        return

    print()
    print(f"═══ Failure Forensics ({len(failed)} / {len(results)} runs) ═══")
    for r in failed:
        m = r["metrics"]
        sh = r.get("state_history", [])
        last_state = sh[-1][1] if sh else "N/A"
        kind = classify_failure(r)
        print()
        print(f"❌ {r['run_id']}  ({kind})")
        print(f"   planner/controller : {r.get('planner')}/{r.get('controller')}")
        print(f"   duration           : {m['M2_duration_s']:.1f} s")
        print(f"   path_len           : {m['M3_path_len_m']:.2f} m")
        print(f"   last_state         : {last_state}")
        print(f"   obs_min            : {m['M6_obs_min_m']:.2f} m")
        print(f"   stuck_count        : {m['M10_stuck_count']}")
        print(f"   recovery total     : {m['M11_recovery_total_n']}"
              f"  (spin={m['M11_recovery_spin_n']}, "
              f"backup={m['M11_recovery_backup_n']}, "
              f"wait={m['M11_recovery_wait_n']}, "
              f"drive={m['M11_recovery_drive_n']})")
        print(f"   planner_failure_n  : {m['M11_planner_failure_n']}")
        print(f"   bt_failure_n       : {m['M7_bt_failure_n']}")
        print(f"   amcl_drift_rms     : {m['M13_amcl_drift_rms']*1000:.1f} mm/s")

    # 분류별 요약
    print()
    print("═══ 실패 분류 요약 ═══")
    by_kind: dict[str, int] = {}
    for r in failed:
        k = classify_failure(r)
        by_kind[k] = by_kind.get(k, 0) + 1
    for k, n in sorted(by_kind.items(), key=lambda x: -x[1]):
        print(f"  {k:<22} : {n}")


def print_per_run_table(results: list[dict]) -> None:
    print()
    headers = [
        "run_id", "P", "C", "rep",
        "dur(s)", "path(m)",
        "XTE", "j_lin", "j_ang", "yaw",
        "obs", "lat(ms)", "stuck", "rec",
        "drift", "rel",
    ]
    widths = [22, 10, 8, 4, 7, 7, 7, 7, 7, 6, 6, 8, 6, 5, 8, 6]
    fmt = "".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print("─" * sum(widths))

    for r in results:
        m = r["metrics"]
        rel = r["reliability"]
        grade_marker = (
            "✅" if rel["grade"] == "RELIABLE"
            else "⚠️" if rel["grade"] == "QUESTIONABLE"
            else "❌"
        )
        row = [
            r["run_id"][:21],
            r.get("planner", "?")[:9],
            r.get("controller", "?")[:7],
            str(r.get("rep", 0)),
            f"{m['M2_duration_s']:.1f}",
            f"{m['M3_path_len_m']:.2f}",
            f"{m['M8_xte_mean_m']:.3f}",
            f"{m['M5_odom_lin_jerk_rms']:.3f}",
            f"{m['M5_odom_ang_jerk_rms']:.3f}",
            f"{m['M12_total_yaw_rad']:.1f}",
            f"{m['M6_obs_min_m']:.2f}",
            f"{m['M9_plan_latency_mean_s']*1000:.0f}",
            str(m['M10_stuck_count']),
            str(m['M11_recovery_total_n']),
            f"{m['M13_amcl_drift_rms']*1000:.1f}mm",
            f"{grade_marker}{rel['score']:.2f}",
        ]
        print(fmt.format(*row))


def print_aggregate_table(agg: dict) -> None:
    print()
    print("═══ Aggregate (mean ± std per planner × controller) ═══")
    headers = ["P", "C", "n", "ok", "rel",
               "dur(s)", "XTE", "j_ang", "yaw", "obs", "lat(ms)", "stuck",
               "drift(mm/s)"]
    widths = [12, 8, 4, 4, 6, 14, 13, 13, 11, 11, 11, 6, 14]
    fmt = "".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print("─" * sum(widths))
    for (p, c), a in sorted(agg.items()):
        dur = a["M2_duration_s"]
        xte = a["M8_xte_mean_m"]
        jang = a["M5_odom_ang_jerk_rms"]
        yaw = a["M12_total_yaw_rad"]
        obs = a["M6_obs_min_m"]
        lat = a["M9_plan_latency_mean_s"]
        stuck = a["M10_stuck_count"]
        drift = a["M13_amcl_drift_rms"]
        row = [
            p[:11],
            c[:7],
            str(a["n"]),
            str(a["completed_n"]),
            f"{a['reliability_mean']:.2f}",
            f"{dur['mean']:.1f}±{dur['std']:.1f}",
            f"{xte['mean']:.3f}±{xte['std']:.3f}",
            f"{jang['mean']:.3f}±{jang['std']:.3f}",
            f"{yaw['mean']:.1f}±{yaw['std']:.1f}",
            f"{obs['mean']:.2f}±{obs['std']:.2f}",
            f"{lat['mean']*1000:.0f}±{lat['std']*1000:.0f}",
            f"{stuck['mean']:.1f}",
            f"{drift['mean']*1000:.1f}±{drift['std']*1000:.1f}",
        ]
        print(fmt.format(*row))


def write_csv(results: list[dict], agg: dict) -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow([
        # 기본
        "run_id", "planner", "controller", "rep",
        "duration_s", "path_len_m", "avg_vel_mps", "max_vel_mps",
        # Stage 별 jerk (controller / smoother / odom)
        "jerk_nav_lin", "jerk_nav_ang",
        "jerk_raw_lin", "jerk_raw_ang",
        "jerk_odom_lin", "jerk_odom_ang",
        # Smoother 관여
        "smth_involvement", "smth_clip_lin_act", "smth_clip_ang_act",
        "smth_jerk_red_lin_pct", "smth_jerk_red_ang_pct",
        # XTE
        "xte_mean_m", "xte_p95_m", "xte_max_m",
        # Planning latency
        "plan_lat_mean_s", "plan_lat_p95_s", "plan_lat_max_s",
        "plan_call_n", "plan_success_n", "plan_failure_n",
        # Stuck events
        "stuck_count", "stuck_total_s", "stuck_max_s",
        # Recovery breakdown
        "rec_planner_fail", "rec_ctrl_fail", "rec_recovery_total",
        "rec_spin", "rec_backup", "rec_wait", "rec_drive", "rec_recovery_fail",
        # Total yaw
        "total_yaw_rad",
        # Obstacle distance distribution
        "obs_min_m", "obs_p10_m", "obs_p50_m", "obs_mean_m",
        # AMCL drift (Step D)
        "amcl_drift_rms", "amcl_drift_p95", "amcl_drift_yaw_rms", "amcl_jump_count",
        # Legacy / 기타
        "bt_failure_n", "plan_pubs",
        "reliability_score", "reliability_grade",
        "odom_hz_raw", "sim_rt_factor_raw",
    ])
    for r in results:
        m = r["metrics"]
        rel = r["reliability"]
        raw = rel["raw"]
        writer.writerow([
            r["run_id"], r.get("planner", "?"), r.get("controller", "?"), r.get("rep", 0),
            m["M2_duration_s"], m["M3_path_len_m"], m["M4_avg_vel_mps"], m["M4_max_vel_mps"],
            m["M5_nav_lin_jerk_rms"], m["M5_nav_ang_jerk_rms"],
            m["M5_raw_lin_jerk_rms"], m["M5_raw_ang_jerk_rms"],
            m["M5_odom_lin_jerk_rms"], m["M5_odom_ang_jerk_rms"],
            m["M5s_involvement_rate"], m["M5s_clip_lin_mean_act"], m["M5s_clip_ang_mean_act"],
            m["M5s_jerk_reduction_lin_pct"], m["M5s_jerk_reduction_ang_pct"],
            m["M8_xte_mean_m"], m["M8_xte_p95_m"], m["M8_xte_max_m"],
            m["M9_plan_latency_mean_s"], m["M9_plan_latency_p95_s"], m["M9_plan_latency_max_s"],
            m["M9_plan_call_n"], m["M9_plan_success_n"], m["M9_plan_failure_n"],
            m["M10_stuck_count"], m["M10_stuck_total_s"], m["M10_stuck_max_s"],
            m["M11_planner_failure_n"], m["M11_controller_failure_n"], m["M11_recovery_total_n"],
            m["M11_recovery_spin_n"], m["M11_recovery_backup_n"],
            m["M11_recovery_wait_n"], m["M11_recovery_drive_n"], m["M11_recovery_failure_n"],
            m["M12_total_yaw_rad"],
            m["M6_obs_min_m"], m["M6_obs_p10_m"], m["M6_obs_p50_m"], m["M6_obs_mean_m"],
            m["M13_amcl_drift_rms"], m["M13_amcl_drift_p95"],
            m["M13_amcl_drift_yaw_rms"], m["M13_amcl_jump_count"],
            m["M7_bt_failure_n"], m["plan_pubs"],
            rel["score"], rel["grade"],
            raw["odom_hz"], raw["sim_rt_factor"],
        ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs_dir", type=Path, help="run 들 들어있는 base 디렉토리")
    parser.add_argument("--csv", action="store_true", help="CSV 출력 (stdout)")
    parser.add_argument("--json", action="store_true", help="JSON 출력 (stdout)")
    parser.add_argument(
        "--completed-only", action="store_true",
        help="완주한 rep 만 집계 (timeout 제외)",
    )
    parser.add_argument(
        "--failure-report", action="store_true",
        help="실패한 run 의 forensics 출력 (stdout, table 대신)",
    )
    args = parser.parse_args()

    if not args.runs_dir.is_dir():
        print(f"❌ not a dir: {args.runs_dir}", file=sys.stderr)
        return 1

    results = analyze_all(args.runs_dir)
    if not results:
        print(f"❌ no bags found under {args.runs_dir}", file=sys.stderr)
        return 1

    if args.failure_report:
        print_failure_report(results)
        return 0

    agg = aggregate(results, completed_only=args.completed_only)

    if args.json:
        # JSON serializable 으로 변환 (tuple key → string key)
        agg_json = {f"{p}__{c}": v for (p, c), v in agg.items()}
        print(json.dumps({"runs": results, "aggregate": agg_json},
                          ensure_ascii=False, indent=2, default=str))
    elif args.csv:
        write_csv(results, agg)
    else:
        if args.completed_only:
            done = [r for r in results if is_completed(r.get("state_history", []))]
            print(f"\n— 완주 only: {len(done)}/{len(results)} runs —")
            print_per_run_table(done)
        else:
            print_per_run_table(results)
        print_aggregate_table(agg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
