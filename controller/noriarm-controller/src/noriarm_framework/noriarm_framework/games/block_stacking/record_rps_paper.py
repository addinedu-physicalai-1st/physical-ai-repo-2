#!/usr/bin/env python3
"""RPS '보' trajectory 녹화 스크립트 (리더-팔로워 텔레옵).

사용법:
    python record_rps_paper.py

절차:
  1. 리더암(토크 OFF) + 팔로워암(토크 ON) 연결
  2. 리더암을 시작 자세로 잡은 뒤 Enter → 팔로워가 해당 자세로 이동
  3. 리더를 움직이면 팔로워가 실시간 미러링
  4. 주먹 두 번 흔들고 보를 내밀기
  5. Enter 또는 Ctrl+C 로 녹화 종료 → rps_paper_trajectory.json 저장
"""
import json
import signal
import sys
import threading
import time
from pathlib import Path

_GESTURE_FILES = {
    "보": "rps_paper_trajectory.json",
    "가위": "rps_scissors_trajectory.json",
    "바위": "rps_rock_trajectory.json",
}
_HZ = 30
_MOTOR_NAMES = [
    "shoulder_pan", "shoulder_lift", "elbow_flex",
    "wrist_flex", "wrist_roll", "gripper",
]

_stop = False


def _sigint(signum, frame):
    global _stop
    _stop = True


def main() -> int:
    global _stop

    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)

    gesture = sys.argv[1] if len(sys.argv) > 1 else "보"
    if gesture not in _GESTURE_FILES:
        print(f"사용법: {sys.argv[0]} [보|가위|바위]")
        return 1
    out = Path(__file__).parent / _GESTURE_FILES[gesture]
    print(f"저장 대상: {out.name}")

    from lerobot.motors.dynamixel.dynamixel import DynamixelMotorsBus
    from lerobot.motors.motors_bus import Motor, MotorNormMode
    from lerobot.robots.omx_follower import OmxFollower
    from lerobot.robots.omx_follower.config_omx_follower import OmxFollowerConfig

    norm = MotorNormMode.RANGE_M100_100

    # 리더암 (토크 OFF — 손으로 자유 이동)
    leader = DynamixelMotorsBus(
        port="/dev/omx_leader",
        motors={
            "shoulder_pan":  Motor(1, "xl330-m288", norm),
            "shoulder_lift": Motor(2, "xl330-m288", norm),
            "elbow_flex":    Motor(3, "xl330-m288", norm),
            "wrist_flex":    Motor(4, "xl330-m288", norm),
            "wrist_roll":    Motor(5, "xl330-m288", norm),
            "gripper":       Motor(6, "xl330-m077", MotorNormMode.RANGE_0_100),
        },
    )

    # 팔로워암 (토크 ON — 리더 위치로 이동)
    follower = OmxFollower(OmxFollowerConfig(port="/dev/omx_follower", cameras={}))

    print("연결 중...")
    leader.connect()
    leader.calibration = leader.read_calibration()
    leader.disable_torque()
    follower.connect()
    print("✓ 리더암(토크 OFF) + 팔로워암(토크 ON) 연결됨")
    print("  리더를 움직이면 팔로워가 바로 따라갑니다.")
    print("\n▶ 시작 자세로 잡은 뒤 Enter = 녹화 시작 / Ctrl+C = 종료")

    recording = False

    def _wait_enter():
        global _stop
        try:
            input()          # 첫 Enter → 녹화 시작
            nonlocal recording
            recording = True
            print(f"● 녹화 시작! ({_HZ}Hz)  주먹 두 번 → 보. 끝나면 Enter 또는 Ctrl+C.")
            input()          # 두 번째 Enter → 녹화 종료
        except (EOFError, KeyboardInterrupt):
            pass
        _stop = True

    threading.Thread(target=_wait_enter, daemon=True).start()

    frames: list[list[float]] = []
    dt = 1.0 / _HZ

    try:
        while not _stop:
            t0 = time.perf_counter()

            pos = leader.sync_read("Present_Position")
            frame = [float(pos[n]) for n in _MOTOR_NAMES]

            action = {f"{n}.pos": frame[i] for i, n in enumerate(_MOTOR_NAMES)}
            follower.send_action(action)

            if recording:
                frames.append(frame)

            elapsed = time.perf_counter() - t0
            rem = dt - elapsed
            if rem > 0:
                time.sleep(rem)
    finally:
        leader.disconnect()
        follower.disconnect()

    print(f"\n■ 녹화 완료: {len(frames)} 프레임 ({len(frames) / _HZ:.1f}초)")

    if len(frames) < 10:
        print("! 프레임이 너무 적습니다. 저장하지 않고 종료합니다.")
        return 1

    data = {"hz": _HZ, "num_frames": len(frames), "trajectory": frames}
    out.write_text(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    print(f"✓ 저장됨: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
