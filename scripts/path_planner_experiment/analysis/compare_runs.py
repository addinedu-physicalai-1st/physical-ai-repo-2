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


def aggregate(results: list[dict]) -> dict:
    """같은 (planner, controller) 의 rep 들을 mean ± std 로 집계."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in results:
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
            1 for r in runs if r.get("state_history")
            and any(s == "RETURNING" for _, s in r["state_history"])
        )
        aggregated[(p, c)] = agg
    return aggregated


def print_per_run_table(results: list[dict]) -> None:
    print()
    headers = [
        "run_id", "P", "C", "rep",
        "dur(s)", "path(m)", "ang_jerk", "lin_jerk",
        "obs(m)", "BT_F", "rel"
    ]
    widths = [22, 10, 8, 4, 7, 7, 9, 9, 7, 5, 6]
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
            f"{m['M5_final_ang_jerk_rms']:.4f}",
            f"{m['M5_final_lin_jerk_rms']:.4f}",
            f"{m['M6_obs_min_m']:.3f}",
            str(m['M7_bt_failure_n']),
            f"{grade_marker}{rel['score']:.2f}",
        ]
        print(fmt.format(*row))


def print_aggregate_table(agg: dict) -> None:
    print()
    print("═══ Aggregate (mean ± std per planner × controller) ═══")
    headers = ["P", "C", "n", "ok", "rel", "dur(s)", "ang_jerk", "obs(m)", "BT_F"]
    widths = [12, 8, 4, 4, 6, 14, 16, 14, 6]
    fmt = "".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print("─" * sum(widths))
    for (p, c), a in sorted(agg.items()):
        dur = a["M2_duration_s"]
        ajk = a["M5_final_ang_jerk_rms"]
        obs = a["M6_obs_min_m"]
        btf = a["M7_bt_failure_n"]
        row = [
            p[:11],
            c[:7],
            str(a["n"]),
            str(a["completed_n"]),
            f"{a['reliability_mean']:.2f}",
            f"{dur['mean']:.1f}±{dur['std']:.1f}",
            f"{ajk['mean']:.4f}±{ajk['std']:.4f}",
            f"{obs['mean']:.3f}±{obs['std']:.3f}",
            f"{btf['mean']:.1f}",
        ]
        print(fmt.format(*row))


def write_csv(results: list[dict], agg: dict) -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow([
        "run_id", "planner", "controller", "rep",
        "duration_s", "path_len_m", "avg_vel_mps",
        "final_ang_jerk_rms", "final_lin_jerk_rms",
        "nav_ang_jerk_rms", "nav_lin_jerk_rms",
        "obs_min_m", "bt_failure_n", "plan_pubs",
        "reliability_score", "reliability_grade",
        "odom_hz_raw", "sim_rt_factor_raw",
    ])
    for r in results:
        m = r["metrics"]
        rel = r["reliability"]
        raw = rel["raw"]
        writer.writerow([
            r["run_id"], r.get("planner", "?"), r.get("controller", "?"), r.get("rep", 0),
            m["M2_duration_s"], m["M3_path_len_m"], m["M4_avg_vel_mps"],
            m["M5_final_ang_jerk_rms"], m["M5_final_lin_jerk_rms"],
            m["M5_nav_ang_jerk_rms"], m["M5_nav_lin_jerk_rms"],
            m["M6_obs_min_m"], m["M7_bt_failure_n"], m["plan_pubs"],
            rel["score"], rel["grade"],
            raw["odom_hz"], raw["sim_rt_factor"],
        ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs_dir", type=Path, help="run 들 들어있는 base 디렉토리")
    parser.add_argument("--csv", action="store_true", help="CSV 출력 (stdout)")
    parser.add_argument("--json", action="store_true", help="JSON 출력 (stdout)")
    args = parser.parse_args()

    if not args.runs_dir.is_dir():
        print(f"❌ not a dir: {args.runs_dir}", file=sys.stderr)
        return 1

    results = analyze_all(args.runs_dir)
    if not results:
        print(f"❌ no bags found under {args.runs_dir}", file=sys.stderr)
        return 1

    agg = aggregate(results)

    if args.json:
        # JSON serializable 으로 변환 (tuple key → string key)
        agg_json = {f"{p}__{c}": v for (p, c), v in agg.items()}
        print(json.dumps({"runs": results, "aggregate": agg_json},
                          ensure_ascii=False, indent=2, default=str))
    elif args.csv:
        write_csv(results, agg)
    else:
        print_per_run_table(results)
        print_aggregate_table(agg)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
