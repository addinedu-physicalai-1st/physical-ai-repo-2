#!/usr/bin/env python3
"""RPS '보' trajectory를 lerobot OmxFollower로 직접 재생. ROS 불필요.

사용법:  python rps_player.py [/dev/omx_follower]

동작:
  1. 홈 포즈 → 녹화 첫 프레임 3초 보간
  2. trajectory 재생 (주먹 두 번 + 보 자세)
  3. 보 자세 5초 유지 (손 감지 대기)
  4. SIGTERM 미수신 시 2로 돌아가서 반복
  5. SIGTERM 수신 시 현재 자세 → 홈 포즈 3초 보간 후 종료
"""
import json
import signal
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
_HOME = [2.9785, -59.5703, 53.6621, 52.6855, 0.4395, 58.7402]
_HOLD_S = 5.0

_stop = False


def _lerp_to(robot, target: list[float], duration_s: float) -> None:
    fps = 30
    steps = int(duration_s * fps)
    dt = 1.0 / fps
    try:
        obs = robot.get_observation()
        start = [float(obs[f"{n}.pos"]) for n in _MOTOR_NAMES]
    except Exception:
        start = list(target)
    for i in range(1, steps + 1):
        t = i / steps
        action = {f"{n}.pos": start[j] + (target[j] - start[j]) * t
                  for j, n in enumerate(_MOTOR_NAMES)}
        try:
            robot.send_action(action)
        except Exception:
            break
        time.sleep(dt)


def main() -> int:
    global _stop

    def _sigterm(signum, frame):
        global _stop
        _stop = True

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    once = "--once" in sys.argv
    port = args[0] if len(args) > 0 else "/dev/omx_follower"
    traj = (_TRAJ_JSON.parent / args[1]) if len(args) > 1 else _TRAJ_JSON
    with open(traj) as f:
        data = json.load(f)
    hz: float = float(data.get("hz", 30))
    frames: list = data["trajectory"]
    dt = 1.0 / hz

    config = OmxFollowerConfig(port=port)
    robot = OmxFollower(config)
    robot.connect()
    try:
        # 1. 홈 → 첫 프레임 3초 보간
        if frames and not _stop:
            _lerp_to(robot, frames[0], duration_s=3.0)

        # 2. 루프: trajectory 재생 → 5초 유지 → 반복 (--once 시 1회만)
        while not _stop:
            print("TRAJ_START", flush=True)
            time.sleep(0.5)
            for frame in frames:
                if _stop:
                    break
                t0 = time.perf_counter()
                action = {f"{n}.pos": v for n, v in zip(_MOTOR_NAMES, frame)}
                robot.send_action(action)
                elapsed = time.perf_counter() - t0
                rem = dt - elapsed
                if rem > 0:
                    time.sleep(rem)

            if _stop:
                break

            if once:
                break

            print("READY", flush=True)
            t_hold = time.perf_counter()
            while not _stop and time.perf_counter() - t_hold < _HOLD_S:
                time.sleep(0.05)

            # 보 자세 → 첫 프레임으로 천천히 복귀 후 반복
            if not _stop:
                _lerp_to(robot, frames[0], duration_s=1.5)

        # SIGTERM → 홈 포즈로 3초 복귀
        _lerp_to(robot, _HOME, duration_s=3.0)
    finally:
        robot.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
