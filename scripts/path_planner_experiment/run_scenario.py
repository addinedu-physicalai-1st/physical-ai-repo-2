#!/usr/bin/env python3
"""다단계 시나리오 자동 실행 + 메트릭 추출 → 발표자료/실험 결과물.

시나리오 (다단계): 충전소(시작) → GOTO 수면실 → GOTO 놀이방 → GOTO 놀이방입구-하
                   → RETURNING(복귀 상태). 하나의 rosbag 으로 연속 기록.

per-run 산출물 (results-dir 아래):
  {planner}-{controller}-{rep}.txt   사람이 읽는 메트릭 표 (extract_metrics 출력)
  {planner}-{controller}-{rep}.json  JSON (M2~M15 전 지표 + reliability)
  bags/{planner}-{controller}-{rep}/ rosbag (mcap)

사전 조건 (run_one.py 와 동일):
  - sim.launch.py (+ cmd_vel relay) 가 떠 있음, workspace install 소싱됨
  - planner/controller 는 nav2_params.yaml 에서 미리 세팅 후 노드 재시작
    (이 스크립트는 config 를 바꾸지 않음 — 모델명은 인자로 받아 파일명에만 사용)

사용:
  python3 run_scenario.py --planner Smac2D --controller RPP --rep 1
  python3 run_scenario.py --planner NavFn --controller DWB --rep 2 \
      --route 수면실,놀이방,놀이방입구-하

종료 코드:
  0 정상 / 1 서비스미가용 / 2 GOTO 실패 / 3 RETURNING 실패 / 4 mcap 없음
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

# run_one.py 의 ExperimentRunner / rosbag 헬퍼 재사용 (같은 디렉토리)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rclpy  # noqa: E402

from run_one import ExperimentRunner, start_rosbag, stop_rosbag  # noqa: E402


DEFAULT_ROUTE = ["수면실", "놀이방", "놀이방입구-하"]
DEFAULT_RESULTS_DIR = "/home/leekt/발표자료/실험 결과물"
EXTRACT = Path(__file__).resolve().parent / "analysis" / "extract_metrics.py"


def run_metrics(mcap: Path, txt_out: Path, json_out: Path) -> None:
    """extract_metrics.py 를 subprocess 로 호출해 표(.txt) + JSON 저장."""
    with txt_out.open("w", encoding="utf-8") as f:
        subprocess.run(
            [sys.executable, str(EXTRACT), str(mcap)],
            stdout=f, stderr=subprocess.STDOUT, check=False,
        )
    with json_out.open("w", encoding="utf-8") as f:
        subprocess.run(
            [sys.executable, str(EXTRACT), "--json", str(mcap)],
            stdout=f, stderr=subprocess.DEVNULL, check=False,
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="GogoPing 다단계 시나리오 자동 실행 + 분석")
    ap.add_argument("--planner", required=True, help="planner 이름 (파일명용, 예: Smac2D)")
    ap.add_argument("--controller", required=True, help="controller 이름 (예: RPP)")
    ap.add_argument("--rep", type=int, default=1, help="회차 (default: 1)")
    ap.add_argument(
        "--route", default=",".join(DEFAULT_ROUTE),
        help="콤마구분 vertex 순서 (default: 수면실,놀이방,놀이방입구-하)",
    )
    ap.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR)
    ap.add_argument("--bag-dir", default=None, help="bag base (default: <results>/bags)")
    ap.add_argument("--timeout-goto", type=float, default=300.0)
    ap.add_argument("--timeout-return", type=float, default=300.0)
    ap.add_argument("--skip-teleport", action="store_true")
    ap.add_argument("--no-metrics", action="store_true", help="주행만, 분석 생략")
    args = ap.parse_args()

    route = [v.strip() for v in args.route.split(",") if v.strip()]
    run_id = f"{args.planner}-{args.controller}-{args.rep}"
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    bag_base = Path(args.bag_dir) if args.bag_dir else results_dir / "bags"
    out_dir = bag_base / run_id
    if out_dir.exists() and any(out_dir.iterdir()):
        print(f"❌ {out_dir} 이미 있음 — 다른 --rep 쓰거나 폴더 삭제")
        return 1
    bag_path = out_dir / "bag"

    rclpy.init()
    node = ExperimentRunner()
    rc = 0
    bag = None
    try:
        if not node.wait_services():
            return 1
        if not args.skip_teleport:
            if not node.teleport_to_charger():
                return 1
            if not node.reset_battery():
                return 1
            time.sleep(2.0)  # AMCL 재수렴 + costmap 갱신

        out_dir.mkdir(parents=True, exist_ok=True)
        node.get_logger().info(f"[{run_id}] route={route} → rosbag {bag_path}")
        bag = start_rosbag(bag_path)
        time.sleep(2.0)

        # ── 다단계 GOTO ──
        for i, dest in enumerate(route, 1):
            node.get_logger().info(f"[{run_id}] GOTO {i}/{len(route)} → {dest}")
            if not node.set_goal("GOTO", dest):
                rc = 2
                break
            if not node.wait_for_state(
                targets=["IDLE"], from_states=["GOTO"],
                timeout=args.timeout_goto, label=f"GOTO/{dest}",
            ):
                rc = 2
                break
            time.sleep(1.0)

        # ── RETURNING (복귀 상태) ──
        if rc == 0:
            node.get_logger().info(f"[{run_id}] RETURNING")
            if not node.set_goal("RETURNING"):
                rc = 3
            elif not node.wait_for_state(
                targets=["IDLE", "CHARGING"], from_states=["RETURNING"],
                timeout=args.timeout_return, label="RETURNING",
            ):
                rc = 3

        time.sleep(1.0)
        if bag is not None:
            stop_rosbag(bag)
            bag = None

        meta = {
            "run_id": run_id,
            "planner": args.planner,
            "controller": args.controller,
            "rep": args.rep,
            "route": route,
            "completed": rc == 0,
            "exit_stage": {0: "ok", 2: "goto", 3: "returning"}.get(rc, "?"),
            "state_history": node._state_history,
        }
        (out_dir / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        if bag is not None:
            stop_rosbag(bag)
        node.destroy_node()
        rclpy.shutdown()

    if rc != 0:
        print(f"❌ {run_id} 주행 실패 (rc={rc}) — bag 은 저장됨: {bag_path}")
        return rc

    # ── 메트릭 추출 → {run_id}.txt / .json (발표자료/실험/results) ──
    if args.no_metrics:
        print(f"✅ {run_id} 주행 완료 (분석 생략) — {out_dir}")
        return 0
    mcaps = sorted(bag_path.glob("*.mcap"))
    if not mcaps:
        print(f"❌ mcap 없음: {bag_path}")
        return 4
    txt_out = results_dir / f"{run_id}.txt"
    json_out = results_dir / f"{run_id}.json"
    run_metrics(mcaps[0], txt_out, json_out)
    print(f"✅ {run_id} 완료 → {txt_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
