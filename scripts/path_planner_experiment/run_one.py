#!/usr/bin/env python3
"""1-run 자동화 — 충전소 → 수면실 → 복귀 시나리오.

사전 조건:
  - sim.launch.py + perception.launch.py (또는 cmd_vel relay) 가 떠 있음
  - workspace install 소싱됨
    source /opt/ros/jazzy/setup.zsh
    source ~/pingdergarten/controller/gogoping-controller/install/setup.zsh
    export ROS_DOMAIN_ID=209

사용:
  python3 run_one.py --run-id run_DNR_1 --output-dir /tmp/runs
  python3 run_one.py --run-id test --destination 수면실 --output-dir /tmp/runs

종료 코드:
  0 : 시나리오 정상 완주
  1 : 서비스 미가용 (timeout)
  2 : GOTO 단계 timeout / abort
  3 : RETURNING 단계 timeout / abort
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from gogoping_msgs.srv import SetBatteryLevel, SetGazeboPose, SetGoal


CHARGER_X = 0.53
CHARGER_Y = 12.834519743089727
CHARGER_YAW = 0.0

DEFAULT_DESTINATION = "수면실"
DEFAULT_TIMEOUT_GOTO = 300.0      # 5분
DEFAULT_TIMEOUT_RETURN = 300.0    # 5분
SERVICE_WAIT_TIMEOUT = 10.0       # 서비스 가용 대기

# rosbag 녹화 대상 — sanity 에서 검증된 12 토픽
BAG_TOPICS = [
    "/gogoping/odom",
    "/gogoping/cmd_vel",
    "/gogoping/cmd_vel_nav",
    "/gogoping/cmd_vel_raw",
    "/gogoping/scan_filtered",
    "/tf",
    "/tf_static",
    "/plan",
    "/local_plan",
    "/behavior_tree_log",
    "/gogoping/debug/nav_events",
    "/gogoping/state_str",
    "/rosout",
]


class ExperimentRunner(Node):
    def __init__(self) -> None:
        super().__init__("experiment_runner")
        self._state: str | None = None
        self._state_history: list[tuple[float, str]] = []
        self._t0 = time.monotonic()

        self.create_subscription(
            String, "/gogoping/state_str", self._on_state, 10
        )
        self._teleport = self.create_client(
            SetGazeboPose, "/gogoping/sim/teleport_pose"
        )
        self._battery = self.create_client(
            SetBatteryLevel, "/gogoping/sim/set_battery_level"
        )
        self._setgoal = self.create_client(SetGoal, "/gogoping/set_goal")

    def _on_state(self, msg: String) -> None:
        s = msg.data
        if s != self._state:
            self._state_history.append((time.monotonic() - self._t0, s))
            self.get_logger().info(f"state → {s}")
        self._state = s

    def wait_services(self, timeout: float = SERVICE_WAIT_TIMEOUT) -> bool:
        for name, cli in [
            ("teleport", self._teleport),
            ("battery", self._battery),
            ("set_goal", self._setgoal),
        ]:
            if not cli.wait_for_service(timeout_sec=timeout):
                self.get_logger().error(f"service '{name}' 미가용")
                return False
        return True

    def _call(self, client, request, label: str, timeout: float = 15.0):
        """ROS 서비스 call_async wrapper. gz CLI 백그라운드 호출 때문에
        teleport 는 3~5초 걸릴 수 있어 timeout 을 넉넉히."""
        future = client.call_async(request)
        deadline = time.monotonic() + timeout
        while rclpy.ok() and not future.done():
            rclpy.spin_once(self, timeout_sec=0.1)
            if time.monotonic() > deadline:
                self.get_logger().error(f"{label}: timeout after {timeout}s")
                return None
        return future.result()

    def teleport_to_charger(self, retries: int = 3) -> bool:
        """gz CLI 가 가끔 timeout 내므로 retry."""
        req = SetGazeboPose.Request()
        req.x = CHARGER_X
        req.y = CHARGER_Y
        req.yaw = CHARGER_YAW
        for attempt in range(1, retries + 1):
            res = self._call(self._teleport, req, "teleport")
            if res is None:
                self.get_logger().warning(
                    f"teleport ROS timeout (attempt {attempt}/{retries})"
                )
                time.sleep(1.0)
                continue
            if res.accepted:
                self.get_logger().info(
                    f"teleported to charger ({CHARGER_X:.2f}, {CHARGER_Y:.2f})"
                )
                return True
            self.get_logger().warning(
                f"teleport gz failed (attempt {attempt}/{retries}): {res.reason}"
            )
            time.sleep(1.0)
        self.get_logger().error("teleport: 모든 retry 실패")
        return False

    def reset_battery(self) -> bool:
        req = SetBatteryLevel.Request()
        req.level = 100.0
        res = self._call(self._battery, req, "battery")
        if res is None:
            return False
        if not res.accepted:
            self.get_logger().error(f"battery rejected: {res.reason}")
            return False
        self.get_logger().info("battery → 100%")
        return True

    def set_goal(self, target_state: str, destination_key: str = "") -> bool:
        req = SetGoal.Request()
        req.goal.target_state = target_state
        req.goal.destination_key = destination_key
        res = self._call(self._setgoal, req, f"set_goal({target_state})")
        if res is None:
            return False
        if not res.accepted:
            self.get_logger().error(
                f"set_goal({target_state}) rejected: {res.reason}"
            )
            return False
        self.get_logger().info(
            f"set_goal accepted: {target_state}"
            + (f" → {destination_key}" if destination_key else "")
        )
        return True

    def wait_for_state(
        self,
        targets: list[str],
        from_states: list[str],
        timeout: float,
        label: str,
    ) -> bool:
        """from_states 진입 후 targets 진입까지 대기.

        FSM 이 IDLE → GOTO → IDLE 처럼 진입 전후 같은 state 일 수 있어
        먼저 from_states 에 들어간 뒤 다시 targets 에 도달해야 SUCCESS.
        """
        deadline = time.monotonic() + timeout
        seen_from = False
        self.get_logger().info(
            f"[{label}] waiting from={from_states} → target={targets}"
        )
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self._state in from_states:
                seen_from = True
            if seen_from and self._state in targets:
                elapsed = timeout - (deadline - time.monotonic())
                self.get_logger().info(
                    f"[{label}] reached {self._state} after {elapsed:.1f}s"
                )
                return True
        self.get_logger().error(
            f"[{label}] timeout after {timeout}s "
            f"(last state={self._state}, seen_from={seen_from})"
        )
        return False


def start_rosbag(out_path: Path) -> subprocess.Popen:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ros2", "bag", "record", "-s", "mcap",
        "-o", str(out_path),
        *BAG_TOPICS,
    ]
    return subprocess.Popen(cmd)


def stop_rosbag(proc: subprocess.Popen, timeout: float = 10.0) -> int:
    proc.send_signal(signal.SIGINT)
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="GogoPing 1-run automation")
    parser.add_argument("--run-id", required=True, help="run identifier (폴더명)")
    parser.add_argument(
        "--destination", default=DEFAULT_DESTINATION,
        help=f"vertex name (default: {DEFAULT_DESTINATION})",
    )
    parser.add_argument(
        "--output-dir", default="/tmp/runs",
        help="bag/메타 저장 base dir (default: /tmp/runs)",
    )
    parser.add_argument(
        "--timeout-goto", type=float, default=DEFAULT_TIMEOUT_GOTO,
        help=f"GOTO 단계 timeout (default: {DEFAULT_TIMEOUT_GOTO}s)",
    )
    parser.add_argument(
        "--timeout-return", type=float, default=DEFAULT_TIMEOUT_RETURN,
        help=f"RETURNING 단계 timeout (default: {DEFAULT_TIMEOUT_RETURN}s)",
    )
    parser.add_argument(
        "--skip-teleport", action="store_true",
        help="teleport / battery reset 건너뜀 (디버그)",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir) / args.run_id
    if out_dir.exists():
        # 이전 실패 잔여 디렉토리 — 비어있으면 자동 정리
        if any(out_dir.iterdir()):
            print(f"❌ {out_dir} not empty. Delete or use different --run-id")
            return 1
        out_dir.rmdir()
    bag_path = out_dir / "bag"

    rclpy.init()
    node = ExperimentRunner()

    try:
        # ── 사전 점검 ──
        if not node.wait_services():
            return 1

        # ── 1. 초기화 (out_dir 만들기 전에 — 실패 시 잔재 안 남기게) ──
        if not args.skip_teleport:
            if not node.teleport_to_charger():
                return 1
            if not node.reset_battery():
                return 1
            time.sleep(2.0)  # AMCL 재수렴 + costmap 갱신 대기

        # ── 2. out_dir 생성 + rosbag 시작 ──
        out_dir.mkdir(parents=True)
        node.get_logger().info(f"rosbag → {bag_path}")
        bag = start_rosbag(bag_path)
        time.sleep(2.0)  # bag 안정화

        # ── 3. GOTO 수면실 ──
        if not node.set_goal("GOTO", args.destination):
            stop_rosbag(bag)
            return 2
        if not node.wait_for_state(
            targets=["IDLE"], from_states=["GOTO"],
            timeout=args.timeout_goto, label="GOTO",
        ):
            stop_rosbag(bag)
            return 2

        # ── 4. RETURNING ──
        if not node.set_goal("RETURNING"):
            stop_rosbag(bag)
            return 3
        if not node.wait_for_state(
            targets=["IDLE", "CHARGING"], from_states=["RETURNING"],
            timeout=args.timeout_return, label="RETURNING",
        ):
            stop_rosbag(bag)
            return 3

        # ── 5. rosbag 정지 ──
        time.sleep(1.0)
        stop_rosbag(bag)

        # ── 6. 메타데이터 저장 ──
        meta = {
            "run_id": args.run_id,
            "destination": args.destination,
            "state_history": node._state_history,
            "completed": True,
        }
        with (out_dir / "metadata.json").open("w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        node.get_logger().info(
            f"✅ run '{args.run_id}' completed — {out_dir}"
        )
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    sys.exit(main())
