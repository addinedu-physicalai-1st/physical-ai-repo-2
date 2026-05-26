#!/usr/bin/env python3
"""RPS '보' trajectory를 lerobot OmxFollower로 직접 재생. ROS 불필요.

사용법:  python rps_player.py [/dev/omx_follower]
"""
import json
import sys
import time
from pathlib import Path

from lerobot.robots.omx_follower import OmxFollower
from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig

_TRAJ_JSON = Path(__file__).parent / "rps_paper_trajectory.json"
_MOTOR_NAMES = [
    "shoulder_pan", "shoulder_lift", "elbow_flex",
    "wrist_flex", "wrist_roll", "gripper",
]


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/omx_follower"
    with open(_TRAJ_JSON) as f:
        data = json.load(f)
    hz: int = data["hz"]
    frames: list = data["trajectory"]
    dt = 1.0 / hz

    config = OmxFollowerConfig(port=port)
    robot = OmxFollower(config)
    robot.connect()
    try:
        for frame in frames:
            t0 = time.perf_counter()
            action = {f"{name}.pos": val for name, val in zip(_MOTOR_NAMES, frame)}
            robot.send_action(action)
            elapsed = time.perf_counter() - t0
            rem = dt - elapsed
            if rem > 0:
                time.sleep(rem)
    finally:
        robot.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
